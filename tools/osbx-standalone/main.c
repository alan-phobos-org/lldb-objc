/*
 * osbx-standalone - Standalone Sandbox Filesystem Scanner
 *
 * A native macOS binary that applies a sandbox profile and scans paths
 * for writability. This eliminates LLDB overhead for fast bulk scanning.
 *
 * Usage:
 *   osbx-standalone [options] [paths...]
 *
 * Options:
 *   --profile FILE     Load sandbox profile from FILE (SBPL format)
 *   --sandbox-only     Use sandbox_check() instead of access() (no fs access)
 *   --json             Output results in JSON format
 *   --quiet            Only output writable paths
 *   --paths-from FILE  Read paths to test from FILE (one per line)
 *   --help             Show this help message
 *
 * Examples:
 *   # Run with default restrictive sandbox
 *   ./osbx-standalone
 *
 *   # Run with custom profile matching target app
 *   ./osbx-standalone --profile /path/to/app.sb
 *
 *   # Test sandbox policy only (no actual filesystem access)
 *   ./osbx-standalone --sandbox-only --json
 *
 *   # Scan specific paths
 *   ./osbx-standalone /tmp /var/tmp ~/Documents
 *
 *   # Scan paths from file
 *   ./osbx-standalone --paths-from paths.txt --json
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <errno.h>
#include <sys/stat.h>
#include <pwd.h>
#include <dlfcn.h>

/* sandbox.h is not always available, declare what we need */
extern int sandbox_init(const char *profile, uint64_t flags, char **errorbuf);
extern int sandbox_init_with_parameters(const char *profile, uint64_t flags,
                                        const char *const parameters[],
                                        char **errorbuf);
extern void sandbox_free_error(char *errorbuf);

/* sandbox_check is a private API in libsystem_sandbox.dylib */
typedef int (*sandbox_check_func)(pid_t pid, const char *operation, int type, ...);

#define SANDBOX_FILTER_PATH 1
#define SANDBOX_CHECK_NO_REPORT 0x40

/* Default paths to scan */
static const char *DEFAULT_PATHS[] = {
    "/tmp",
    "/private/tmp",
    "/var/tmp",
    "/private/var/tmp",
    "/var/folders",
    "/dev/null",
    "/dev/zero",
    "/System",
    "/usr",
    "/usr/local",
    "/bin",
    "/sbin",
    "/Applications",
    "/Library",
    "/Users",
    NULL
};

/* Default restrictive sandbox profile */
static const char *DEFAULT_PROFILE =
    "(version 1)\n"
    "(deny default)\n"
    "(allow process-exec*)\n"
    "(allow process-fork)\n"
    "(allow file-read*)\n"
    "(allow file-write* (literal \"/dev/null\"))\n"
    "(allow file-write* (literal \"/dev/zero\"))\n"
    "(allow sysctl-read)\n"
    "(allow mach-lookup)\n";

/* Global state */
static sandbox_check_func g_sandbox_check = NULL;
static int g_json_output = 0;
static int g_quiet = 0;
static int g_sandbox_only = 0;
static int g_first_json_entry = 1;

/* Load sandbox_check dynamically */
static int load_sandbox_check(void) {
    void *handle = dlopen("/usr/lib/system/libsystem_sandbox.dylib", RTLD_LAZY);
    if (!handle) {
        fprintf(stderr, "Warning: Could not load libsystem_sandbox.dylib\n");
        return -1;
    }

    g_sandbox_check = (sandbox_check_func)dlsym(handle, "sandbox_check");
    if (!g_sandbox_check) {
        fprintf(stderr, "Warning: Could not find sandbox_check symbol\n");
        return -1;
    }

    return 0;
}

/* Read file contents into malloc'd buffer */
static char *read_file(const char *path) {
    FILE *f = fopen(path, "r");
    if (!f) {
        fprintf(stderr, "Error: Could not open %s: %s\n", path, strerror(errno));
        return NULL;
    }

    fseek(f, 0, SEEK_END);
    long len = ftell(f);
    fseek(f, 0, SEEK_SET);

    char *buf = malloc(len + 1);
    if (!buf) {
        fclose(f);
        return NULL;
    }

    size_t read_len = fread(buf, 1, len, f);
    buf[read_len] = '\0';
    fclose(f);

    return buf;
}

/* Apply sandbox profile */
static int apply_sandbox_profile(const char *profile_path) {
    char *profile = NULL;

    if (profile_path) {
        profile = read_file(profile_path);
        if (!profile) {
            return -1;
        }
    } else {
        profile = strdup(DEFAULT_PROFILE);
        if (!profile) {
            return -1;
        }
    }

    char *error = NULL;
    int ret = sandbox_init(profile, 0, &error);

    if (ret != 0) {
        fprintf(stderr, "sandbox_init failed: %s\n", error ? error : "unknown error");
        if (error) {
            sandbox_free_error(error);
        }
        free(profile);
        return -1;
    }

    free(profile);
    return 0;
}

/* Check if path is writable using access() syscall */
static int check_writable_access(const char *path) {
    return access(path, W_OK) == 0;
}

/* Check if sandbox allows write using sandbox_check() */
static int check_writable_sandbox(const char *path) {
    if (!g_sandbox_check) {
        fprintf(stderr, "Error: sandbox_check not available\n");
        return 0;
    }

    /* SANDBOX_FILTER_PATH | SANDBOX_CHECK_NO_REPORT */
    int result = g_sandbox_check(getpid(), "file-write-data",
                                  SANDBOX_FILTER_PATH | SANDBOX_CHECK_NO_REPORT,
                                  path);
    return result == 0;
}

/* Get path type as string */
static const char *get_path_type(const char *path) {
    struct stat st;
    if (lstat(path, &st) != 0) {
        return "not_found";
    }

    if (S_ISDIR(st.st_mode)) return "directory";
    if (S_ISREG(st.st_mode)) return "file";
    if (S_ISLNK(st.st_mode)) return "symlink";
    if (S_ISCHR(st.st_mode)) return "device";
    if (S_ISBLK(st.st_mode)) return "device";
    if (S_ISFIFO(st.st_mode)) return "fifo";
    if (S_ISSOCK(st.st_mode)) return "socket";

    return "unknown";
}

/* Escape string for JSON output */
static void print_json_string(const char *s) {
    putchar('"');
    for (; *s; s++) {
        switch (*s) {
            case '"':  printf("\\\""); break;
            case '\\': printf("\\\\"); break;
            case '\n': printf("\\n"); break;
            case '\r': printf("\\r"); break;
            case '\t': printf("\\t"); break;
            default:   putchar(*s); break;
        }
    }
    putchar('"');
}

/* Output a single result */
static void output_result(const char *path, int writable, const char *type) {
    if (g_json_output) {
        if (writable) {
            if (!g_first_json_entry) {
                printf(",\n");
            }
            printf("    {\"path\": ");
            print_json_string(path);
            printf(", \"type\": \"%s\"}", type);
            g_first_json_entry = 0;
        }
    } else {
        if (writable) {
            printf("WRITABLE: %s (%s)\n", path, type);
        } else if (!g_quiet) {
            printf("DENIED:   %s (%s)\n", path, type);
        }
    }
}

/* Expand ~ in path */
static char *expand_path(const char *path) {
    if (path[0] != '~') {
        return strdup(path);
    }

    const char *home = getenv("HOME");
    if (!home) {
        struct passwd *pw = getpwuid(getuid());
        if (pw) {
            home = pw->pw_dir;
        }
    }

    if (!home) {
        return strdup(path);
    }

    size_t home_len = strlen(home);
    size_t path_len = strlen(path);
    char *expanded = malloc(home_len + path_len);
    if (!expanded) {
        return strdup(path);
    }

    strcpy(expanded, home);
    strcat(expanded, path + 1);
    return expanded;
}

/* Print usage */
static void print_usage(const char *prog) {
    printf("Usage: %s [options] [paths...]\n", prog);
    printf("\n");
    printf("Standalone sandbox filesystem scanner.\n");
    printf("\n");
    printf("Options:\n");
    printf("  --profile FILE     Load sandbox profile from FILE (SBPL format)\n");
    printf("  --sandbox-only     Use sandbox_check() instead of access()\n");
    printf("  --json             Output results in JSON format\n");
    printf("  --quiet            Only output writable paths\n");
    printf("  --paths-from FILE  Read paths to test from FILE (one per line)\n");
    printf("  --no-sandbox       Skip applying sandbox profile\n");
    printf("  --help             Show this help message\n");
    printf("\n");
    printf("Examples:\n");
    printf("  %s                           # Scan with default sandbox\n", prog);
    printf("  %s --profile app.sb          # Use custom profile\n", prog);
    printf("  %s --sandbox-only --json     # Policy check only, JSON output\n", prog);
    printf("  %s /tmp /var ~/Documents     # Scan specific paths\n", prog);
}

int main(int argc, char *argv[]) {
    const char *profile_path = NULL;
    const char *paths_file = NULL;
    int no_sandbox = 0;
    char **custom_paths = NULL;
    int custom_path_count = 0;

    /* Parse arguments */
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--profile") == 0 && i + 1 < argc) {
            profile_path = argv[++i];
        } else if (strcmp(argv[i], "--sandbox-only") == 0) {
            g_sandbox_only = 1;
        } else if (strcmp(argv[i], "--json") == 0) {
            g_json_output = 1;
        } else if (strcmp(argv[i], "--quiet") == 0) {
            g_quiet = 1;
        } else if (strcmp(argv[i], "--paths-from") == 0 && i + 1 < argc) {
            paths_file = argv[++i];
        } else if (strcmp(argv[i], "--no-sandbox") == 0) {
            no_sandbox = 1;
        } else if (strcmp(argv[i], "--help") == 0 || strcmp(argv[i], "-h") == 0) {
            print_usage(argv[0]);
            return 0;
        } else if (argv[i][0] != '-') {
            /* Collect custom paths */
            custom_paths = realloc(custom_paths, (custom_path_count + 1) * sizeof(char *));
            custom_paths[custom_path_count++] = argv[i];
        } else {
            fprintf(stderr, "Unknown option: %s\n", argv[i]);
            print_usage(argv[0]);
            return 1;
        }
    }

    /* Load sandbox_check if needed */
    if (g_sandbox_only) {
        if (load_sandbox_check() != 0) {
            fprintf(stderr, "Error: --sandbox-only requires sandbox_check()\n");
            return 1;
        }
    }

    /* Apply sandbox profile */
    if (!no_sandbox) {
        if (apply_sandbox_profile(profile_path) != 0) {
            return 1;
        }
    }

    /* Collect paths to scan */
    const char **paths_to_scan = NULL;
    int path_count = 0;

    if (paths_file) {
        /* Read paths from file */
        char *content = read_file(paths_file);
        if (!content) {
            return 1;
        }

        /* Count lines */
        int lines = 0;
        for (char *p = content; *p; p++) {
            if (*p == '\n') lines++;
        }
        lines++; /* Last line might not have newline */

        paths_to_scan = malloc((lines + 1) * sizeof(char *));
        char *line = strtok(content, "\n");
        while (line) {
            if (line[0] && line[0] != '#') {
                paths_to_scan[path_count++] = expand_path(line);
            }
            line = strtok(NULL, "\n");
        }
        paths_to_scan[path_count] = NULL;
        /* Note: content is kept allocated for path strings */
    } else if (custom_path_count > 0) {
        /* Use custom paths from command line */
        paths_to_scan = malloc((custom_path_count + 1) * sizeof(char *));
        for (int i = 0; i < custom_path_count; i++) {
            paths_to_scan[i] = expand_path(custom_paths[i]);
        }
        paths_to_scan[custom_path_count] = NULL;
        path_count = custom_path_count;
    } else {
        /* Use default paths */
        paths_to_scan = DEFAULT_PATHS;
        for (path_count = 0; DEFAULT_PATHS[path_count]; path_count++);
    }

    /* Output JSON header */
    if (g_json_output) {
        printf("{\n");
        printf("  \"sandbox_applied\": %s,\n", no_sandbox ? "false" : "true");
        printf("  \"check_method\": \"%s\",\n", g_sandbox_only ? "sandbox_check" : "access");
        printf("  \"paths_tested\": %d,\n", path_count);
        printf("  \"writable_paths\": [\n");
    }

    /* Scan all paths */
    int writable_count = 0;
    for (int i = 0; paths_to_scan[i]; i++) {
        const char *path = paths_to_scan[i];
        const char *type = get_path_type(path);

        int writable;
        if (g_sandbox_only) {
            writable = check_writable_sandbox(path);
        } else {
            writable = check_writable_access(path);
        }

        output_result(path, writable, type);
        if (writable) {
            writable_count++;
        }
    }

    /* Output JSON footer */
    if (g_json_output) {
        printf("\n  ],\n");
        printf("  \"writable_count\": %d\n", writable_count);
        printf("}\n");
    } else if (!g_quiet) {
        printf("\nTotal: %d/%d paths writable\n", writable_count, path_count);
    }

    /* Cleanup */
    free(custom_paths);

    return 0;
}
