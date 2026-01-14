"""
Unit tests for objc_sandbox.py pure Python functions.

These tests cover path generation, pattern matching, and output formatting
that doesn't require LLDB runtime.
"""

import json
import os
import pytest
import sys
import tempfile

# Add scripts directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../scripts"))

from objc_sandbox import (
    matches_filter,
    should_skip_path,
    escape_objc_string,
    generate_test_paths,
    format_output_json,
    format_progress,
    ScanLogger,
    DEFAULT_IGNORE_PATTERNS,
)


class TestMatchesFilter:
    """Tests for matches_filter() function."""

    @pytest.mark.sandbox
    def test_empty_filters_match_all(self):
        """Empty filter list should match everything."""
        assert matches_filter("/tmp/foo", []) is True
        assert matches_filter("/var/bar", []) is True

    @pytest.mark.sandbox
    def test_glob_pattern_basic(self):
        """Should match basic glob patterns."""
        assert matches_filter("/tmp/foo", ["/tmp/*"]) is True
        assert matches_filter("/var/foo", ["/tmp/*"]) is False

    @pytest.mark.sandbox
    def test_glob_pattern_recursive(self):
        """Should match recursive glob patterns."""
        assert matches_filter("/tmp/foo/bar", ["/tmp/**"]) is True
        assert matches_filter("/tmp/foo/bar/baz", ["/tmp/**"]) is True
        assert matches_filter("/var/tmp", ["/tmp/**"]) is False

    @pytest.mark.sandbox
    def test_regex_pattern(self):
        """Should match regex patterns."""
        assert matches_filter("/var/mobile/Library/Caches", [".*Caches.*"]) is True
        assert matches_filter("/var/mobile/Documents", [".*Caches.*"]) is False

    @pytest.mark.sandbox
    def test_multiple_filters_or_logic(self):
        """Multiple filters should use OR logic."""
        filters = ["/tmp/**", "/var/**"]
        assert matches_filter("/tmp/foo", filters) is True
        assert matches_filter("/var/bar", filters) is True
        assert matches_filter("/System/foo", filters) is False

    @pytest.mark.sandbox
    def test_invalid_regex_ignored(self):
        """Invalid regex patterns should be ignored."""
        # This invalid regex should not crash, just not match
        assert matches_filter("/tmp/foo", ["[invalid"]) is False


class TestShouldSkipPath:
    """Tests for should_skip_path() function."""

    @pytest.mark.sandbox
    def test_skip_system_paths(self):
        """Should skip system paths matching default ignore patterns."""
        assert should_skip_path("/System/Library/foo", ["/System/**"]) is True
        assert should_skip_path("/usr/bin/ls", ["/usr/**"]) is True

    @pytest.mark.sandbox
    def test_skip_app_bundles(self):
        """Should skip app bundle contents."""
        assert should_skip_path("/Applications/Safari.app/Contents/MacOS/Safari", ["*.app/Contents/*"]) is True

    @pytest.mark.sandbox
    def test_skip_git_directories(self):
        """Should skip .git directories."""
        assert should_skip_path("/Users/test/project/.git/objects", ["*/.git/*"]) is True

    @pytest.mark.sandbox
    def test_no_skip_regular_paths(self):
        """Should not skip regular paths."""
        assert should_skip_path("/tmp/foo", ["/System/**"]) is False
        assert should_skip_path("/var/folders/test", ["/System/**"]) is False


class TestEscapeObjcString:
    """Tests for escape_objc_string() function."""

    @pytest.mark.sandbox
    def test_escape_quotes(self):
        """Should escape double quotes."""
        assert escape_objc_string('path with "quotes"') == 'path with \\"quotes\\"'

    @pytest.mark.sandbox
    def test_escape_backslashes(self):
        """Should escape backslashes."""
        assert escape_objc_string("path\\with\\backslashes") == "path\\\\with\\\\backslashes"

    @pytest.mark.sandbox
    def test_no_escape_needed(self):
        """Should pass through normal paths unchanged."""
        assert escape_objc_string("/tmp/foo/bar") == "/tmp/foo/bar"

    @pytest.mark.sandbox
    def test_combined_escaping(self):
        """Should handle both quotes and backslashes."""
        assert escape_objc_string('path\\"mixed"') == 'path\\\\\\"mixed\\"'


class TestGenerateTestPaths:
    """Tests for generate_test_paths() function."""

    @pytest.mark.sandbox
    def test_macos_paths_no_container(self):
        """Should generate macOS paths without container."""
        paths = generate_test_paths(None, None, "macOS", quick=False)
        assert "/tmp" in paths
        assert "/private/tmp" in paths
        assert "/dev/null" in paths

    @pytest.mark.sandbox
    def test_macos_paths_with_container(self):
        """Should expand container templates for macOS."""
        container = "/Users/test/Library/Containers/com.example.app/Data"
        paths = generate_test_paths(container, None, "macOS", quick=False)

        # Container paths should be expanded
        assert f"{container}/Documents" in paths
        assert f"{container}/Library" in paths

        # No template markers should remain
        for path in paths:
            assert "{{CONTAINER}}" not in path

    @pytest.mark.sandbox
    def test_ios_paths_with_container(self):
        """Should generate iOS-specific paths."""
        container = "/var/mobile/Containers/Data/Application/ABC123"
        paths = generate_test_paths(container, None, "iOS", quick=False)

        # iOS-specific paths
        assert f"{container}/Documents" in paths
        assert "/var/mobile/Containers/Shared/AppGroup" in paths

    @pytest.mark.sandbox
    def test_quick_mode_fewer_paths(self):
        """Quick mode should return fewer paths."""
        container = "/Users/test"
        quick_paths = generate_test_paths(container, None, "macOS", quick=True)
        full_paths = generate_test_paths(container, None, "macOS", quick=False)

        assert len(quick_paths) < len(full_paths)
        assert len(quick_paths) <= 20  # Quick should be ~20 paths

    @pytest.mark.sandbox
    def test_temp_directory_added(self):
        """Temp directory should be added if provided."""
        container = "/var/mobile/Containers/Data/Application/ABC123"
        temp = "/private/var/mobile/Containers/Data/Application/ABC123/tmp"
        paths = generate_test_paths(container, temp, "iOS", quick=False)

        assert temp in paths

    @pytest.mark.sandbox
    def test_no_duplicate_temp(self):
        """Temp directory should not be duplicated."""
        container = "/Users/test/Library/Containers/com.example.app/Data"
        temp = f"{container}/tmp"  # Already included in template paths
        paths = generate_test_paths(container, temp, "macOS", quick=False)

        # Should only appear once
        assert paths.count(temp) == 1


class TestFormatOutputJson:
    """Tests for format_output_json() function."""

    @pytest.mark.sandbox
    def test_json_structure(self):
        """JSON output should have correct structure."""
        writable = [{"path": "/tmp", "type": "directory", "note": None}]
        denied = [{"path": "/System", "reason": "sip_protected"}]

        output = format_output_json(writable, denied, "macOS", "/Users/test", "/private/tmp", True, 10, 0.5, "quick")
        data = json.loads(output)

        assert data["platform"] == "macOS"
        assert data["container"] == "/Users/test"
        assert data["temp_directory"] == "/private/tmp"
        assert data["sandbox_active"] is True
        assert data["tested_count"] == 10
        assert data["writable_count"] == 1
        assert data["duration_seconds"] == 0.5
        assert data["scan_mode"] == "quick"
        assert len(data["writable_paths"]) == 1
        assert len(data["denied_paths"]) == 1

    @pytest.mark.sandbox
    def test_json_valid(self):
        """Output should be valid JSON."""
        output = format_output_json([], [], "iOS", None, None, False, 0, 0.1, "default")
        # Should not raise
        data = json.loads(output)
        assert isinstance(data, dict)


class TestDefaultIgnorePatterns:
    """Tests for default ignore patterns."""

    @pytest.mark.sandbox
    def test_system_paths_ignored(self):
        """System paths should be ignored by default."""
        assert should_skip_path("/System/Library/Frameworks", DEFAULT_IGNORE_PATTERNS) is True
        assert should_skip_path("/usr/bin/ls", DEFAULT_IGNORE_PATTERNS) is True
        assert should_skip_path("/bin/sh", DEFAULT_IGNORE_PATTERNS) is True

    @pytest.mark.sandbox
    def test_user_paths_not_ignored(self):
        """User paths should not be ignored by default."""
        assert should_skip_path("/tmp/foo", DEFAULT_IGNORE_PATTERNS) is False
        assert should_skip_path("/var/folders/test", DEFAULT_IGNORE_PATTERNS) is False

    @pytest.mark.sandbox
    def test_app_bundles_ignored(self):
        """App bundle contents should be ignored."""
        assert should_skip_path("/Applications/Safari.app/Contents/Resources/foo", DEFAULT_IGNORE_PATTERNS) is True


# Parametrized tests for comprehensive coverage
class TestMatchesFilterParametrized:
    """Parametrized tests for matches_filter edge cases."""

    @pytest.mark.sandbox
    @pytest.mark.parametrize(
        "path,filters,expected",
        [
            # Glob patterns - note: fnmatch's * matches / unlike shell glob
            ("/tmp/foo", ["/tmp/*"], True),
            ("/tmp/foo/bar", ["/tmp/*"], True),  # fnmatch * matches /
            ("/tmp/foo/bar", ["/tmp/**"], True),  # ** matches recursively
            # Regex patterns
            ("/var/mobile/Library/Caches", [".*Caches"], True),
            ("/var/mobile/Library/Caches/foo", [".*Caches"], True),  # Partial match
            # Case sensitivity (glob is case-sensitive by default)
            ("/TMP/foo", ["/tmp/*"], False),
            # Multiple patterns
            ("/opt/test", ["/tmp/*", "/var/*", "/opt/*"], True),
        ],
    )
    def test_various_filter_cases(self, path, filters, expected):
        """Should correctly handle various filter patterns."""
        assert matches_filter(path, filters) is expected


class TestGenerateTestPathsParametrized:
    """Parametrized tests for generate_test_paths edge cases."""

    @pytest.mark.sandbox
    @pytest.mark.parametrize(
        "platform,expected_path",
        [
            ("macOS", "/usr/local"),
            ("macOS", "~/Library/Caches"),  # Tilde for non-sandboxed
            ("iOS", "/var/mobile/Containers/Shared/AppGroup"),
            ("iOS", "/private/var/mobile/Library/SMS"),
        ],
    )
    def test_platform_specific_paths(self, platform, expected_path):
        """Should include platform-specific paths."""
        paths = generate_test_paths(None, None, platform, quick=False)
        # Note: some paths may be templates or tilde-prefixed
        found = any(expected_path in p or p.endswith(expected_path.lstrip("~")) for p in paths)
        assert found, f"Expected {expected_path} to be in paths for {platform}"


class TestFormatProgress:
    """Tests for format_progress() function."""

    @pytest.mark.sandbox
    def test_progress_basic(self):
        """Should format basic progress string."""
        import time

        start = time.time()
        progress = format_progress(50, 100, 5, start)
        assert "50/100" in progress
        assert "50%" in progress
        assert "5 writable" in progress

    @pytest.mark.sandbox
    def test_progress_zero_total(self):
        """Should handle zero total gracefully."""
        import time

        progress = format_progress(0, 0, 0, time.time())
        assert "Scanning" in progress

    @pytest.mark.sandbox
    def test_progress_complete(self):
        """Should show 100% when complete."""
        import time

        progress = format_progress(100, 100, 10, time.time())
        assert "100%" in progress
        assert "ETA" not in progress  # No ETA when complete


class TestScanLogger:
    """Tests for ScanLogger class."""

    @pytest.mark.sandbox
    def test_logger_creates_file(self):
        """Logger should create log file with correct format."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
            log_path = f.name

        try:
            logger = ScanLogger(log_path)
            logger.log_check("/tmp/test", "writable", "directory", "-")
            logger.log_check("/System", "not_writable", "directory", "sip_protected")
            logger.write({"platform": "macOS", "container": "/Users/test"})

            with open(log_path, "r") as f:
                content = f.read()

            # Check header
            assert "# osbx scan log" in content
            assert "Platform: macOS" in content
            assert "Container: /Users/test" in content

            # Check column headers
            assert "PATH\tRESULT\tTYPE\tREASON\tDETAILS" in content

            # Check entries
            assert "/tmp/test\twritable\tdirectory" in content
            assert "/System\tnot_writable\tdirectory\tsip_protected" in content
        finally:
            os.unlink(log_path)

    @pytest.mark.sandbox
    def test_logger_counts_writable(self):
        """Logger should correctly count writable paths."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
            log_path = f.name

        try:
            logger = ScanLogger(log_path)
            logger.log_check("/tmp", "writable", "directory", "-")
            logger.log_check("/var", "writable", "directory", "-")
            logger.log_check("/System", "not_writable", "directory", "sip_protected")
            logger.write({"platform": "macOS"})

            with open(log_path, "r") as f:
                content = f.read()

            # Should show 2 writable paths
            assert "Writable: 2" in content
            assert "Paths tested: 3" in content
        finally:
            os.unlink(log_path)

    @pytest.mark.sandbox
    def test_logger_with_filter(self):
        """Logger should include filter in header if provided."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
            log_path = f.name

        try:
            logger = ScanLogger(log_path)
            logger.log_check("/tmp/foo", "writable", "directory", "-")
            logger.write({"platform": "iOS", "filter": "/tmp/**"})

            with open(log_path, "r") as f:
                content = f.read()

            assert "# Filter: /tmp/**" in content
        finally:
            os.unlink(log_path)


class TestFormatOutputJsonInterrupted:
    """Tests for interrupted flag in JSON output."""

    @pytest.mark.sandbox
    def test_json_includes_interrupted_false(self):
        """JSON output should include interrupted: false by default."""
        output = format_output_json([], [], "macOS", None, None, False, 0, 0.1, "default")
        data = json.loads(output)
        assert data["interrupted"] is False

    @pytest.mark.sandbox
    def test_json_includes_interrupted_true(self):
        """JSON output should include interrupted: true when set."""
        output = format_output_json([], [], "macOS", None, None, False, 0, 0.1, "default", interrupted=True)
        data = json.loads(output)
        assert data["interrupted"] is True
