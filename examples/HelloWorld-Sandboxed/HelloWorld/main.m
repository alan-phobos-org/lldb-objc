#import <Foundation/Foundation.h>

// sandbox.h is deprecated but sandbox_init still works for testing
#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wdeprecated-declarations"

// Sandbox profile: restrictive but functional
// Uses kSBXProfileNoNetwork builtin as base, which:
// - Allows file operations
// - Denies network access
// Then we'll use a custom profile to restrict writes
static const char *SANDBOX_PROFILE_NETWORK = "no-network";

// Custom write-restricted profile for testing
// Start permissive, then restrict specific things
static const char *SANDBOX_PROFILE_CUSTOM =
    "(version 1)\n"
    // Allow everything by default
    "(allow default)\n"
    // Deny network access
    "(deny network*)\n"
    // Deny writes except to specific paths
    "(deny file-write*)\n"
    "(allow file-write* (subpath \"/private/tmp\"))\n"
    "(allow file-write* (subpath \"/tmp\"))\n"
    "(allow file-write* (subpath \"/dev\"))\n";

@interface Greeter : NSObject {
    NSString *_greeting;
    NSDictionary *_metadata;
    NSInteger _count;
    NSDictionary *_nestedData;
}
- (void)sayHello:(NSString *)name;
- (NSInteger)add:(NSInteger)a to:(NSInteger)b;
@end

@implementation Greeter

- (instancetype)init {
    self = [super init];
    if (self) {
        _greeting = @"Hello";
        _count = 0;

        _nestedData = @{
            @"fruits": @[@"apple", @"banana", @"cherry", @"date", @"elderberry"],
            @"colors": @[@"red", @"green", @"blue", @"yellow", @"purple"],
            @"cities": @[@"Tokyo", @"Paris", @"London", @"Sydney", @"Cairo"]
        };

        _metadata = @{
            @"version": @"1.0",
            @"author": @"Test",
            @"nested": _nestedData,
            @"sandboxed": @YES
        };
    }
    return self;
}

- (void)sayHello:(NSString *)name {
    NSLog(@"Hello, %@! (from sandboxed process)", name);
    NSLog(@"Nested data has %lu keys", (unsigned long)[_nestedData count]);
}

- (NSInteger)add:(NSInteger)a to:(NSInteger)b {
    NSInteger result = a + b;
    NSLog(@"%ld + %ld = %ld", (long)a, (long)b, (long)result);
    return result;
}

@end

extern int sandbox_init(const char *profile, uint64_t flags, char **errorbuf);
extern void sandbox_free_error(char *errorbuf);
extern int sandbox_check(pid_t pid, const char *operation, int type, ...);

#define SANDBOX_NAMED 0x0001
#define SANDBOX_NAMED_BUILTIN 0x0002
#define SANDBOX_CHECK_NO_REPORT 0x0002

int main(int argc, const char * argv[]) {
    @autoreleasepool {
        NSLog(@"Starting HelloWorld-Sandboxed...");

        // Initialize sandbox with our restrictive profile
        char *errbuf = NULL;
        int result = sandbox_init(SANDBOX_PROFILE_CUSTOM, 0, &errbuf);

        if (result != 0) {
            NSLog(@"Sandbox init failed: %s", errbuf ? errbuf : "unknown error");
            if (errbuf) sandbox_free_error(errbuf);
            return 1;
        }

        NSLog(@"Sandbox initialized successfully!");
        NSLog(@"Profile: write only to /tmp, /private/tmp, /dev");
        NSLog(@"Network access: DENIED");

        Greeter *greeter = [[Greeter alloc] init];
        [greeter sayHello:@"World"];
        [greeter sayHello:@"LLDB"];

        NSInteger sum = [greeter add:42 to:58];
        NSLog(@"Sum is: %ld", (long)sum);

        // Verify sandbox is active using sandbox_check
        // sandbox_check returns 0 if operation is allowed, non-zero if denied
        pid_t pid = getpid();

        // Check if we're denied write access to /System (should be denied)
        int systemCheck = sandbox_check(pid, "file-write-data", SANDBOX_CHECK_NO_REPORT, "/System");
        NSLog(@"sandbox_check /System write: %s", systemCheck != 0 ? "DENIED" : "allowed");

        // Check if we're denied write access to /var (should be denied)
        int varCheck = sandbox_check(pid, "file-write-data", SANDBOX_CHECK_NO_REPORT, "/var");
        NSLog(@"sandbox_check /var write: %s", varCheck != 0 ? "DENIED" : "allowed");

        // Check if we're denied write access to home directory (should be denied)
        NSString *homePath = NSHomeDirectory();
        int homeCheck = sandbox_check(pid, "file-write-data", SANDBOX_CHECK_NO_REPORT, [homePath UTF8String]);
        NSLog(@"sandbox_check %@ write: %s", homePath, homeCheck != 0 ? "DENIED" : "allowed");

        // Check network access (should be denied)
        int networkCheck = sandbox_check(pid, "network-outbound", SANDBOX_CHECK_NO_REPORT, "");
        NSLog(@"sandbox_check network: %s", networkCheck != 0 ? "DENIED" : "allowed");

        // Summary of sandbox status
        BOOL sandboxActive = (systemCheck != 0 || varCheck != 0);
        NSLog(@"Sandbox active: %@", sandboxActive ? @"YES" : @"NO");

        NSLog(@"Done!");
    }
    return 0;
}

#pragma clang diagnostic pop
