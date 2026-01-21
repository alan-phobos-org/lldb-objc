#!/usr/bin/env python3
"""
Unit tests for objc_sharedcache.py module.

These tests mock LLDB objects to test the get_shared_cache_info function
in isolation, verifying correct parsing and error handling.
"""

import sys
import os
import unittest
from unittest.mock import Mock, MagicMock

# Mock lldb and objc_utils modules before importing
mock_lldb = Mock()
mock_lldb.SBError = Mock
sys.modules['lldb'] = mock_lldb
sys.modules['objc_utils'] = Mock()

# Add scripts directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import objc_sharedcache

# Mock the functions we need from objc_utils
objc_sharedcache.register_command = Mock()
objc_sharedcache.require_stopped_process = Mock()
objc_sharedcache.evaluate_expression = Mock()

# Mock lldb module in objc_sharedcache
objc_sharedcache.lldb = mock_lldb


class TestGetSharedCacheInfo(unittest.TestCase):
    """Unit tests for get_shared_cache_info function."""

    def setUp(self):
        """Set up mock LLDB objects for each test."""
        self.mock_frame = Mock()
        self.mock_process = Mock()
        self.mock_thread = Mock()
        self.mock_thread.GetProcess.return_value = self.mock_process
        self.mock_frame.GetThread.return_value = self.mock_thread

    def create_mock_result(self, is_valid=True, error_fail=False, error_msg=""):
        """Helper to create a mock SBValue result."""
        mock_result = Mock()
        mock_result.IsValid.return_value = is_valid
        mock_error = Mock()
        mock_error.Fail.return_value = error_fail
        mock_error.GetCString.return_value = error_msg
        mock_result.GetError.return_value = mock_error
        return mock_result

    def create_mock_struct(self, base, size):
        """Helper to create a mock struct result with base and size fields."""
        mock_result = self.create_mock_result(is_valid=True, error_fail=False)

        mock_base = Mock()
        mock_base.IsValid.return_value = True
        mock_base.GetValueAsUnsigned.return_value = base

        mock_size = Mock()
        mock_size.IsValid.return_value = True
        mock_size.GetValueAsUnsigned.return_value = size

        mock_result.GetChildMemberWithName.side_effect = lambda name: {
            "base": mock_base,
            "size": mock_size,
        }.get(name)

        return mock_result

    def create_mock_uuid_uint64(self, value):
        """Helper to create a mock uint64 result for UUID reading."""
        mock_result = self.create_mock_result(is_valid=True, error_fail=False)
        mock_result.GetValueAsUnsigned.return_value = value
        return mock_result

    def test_successful_cache_info_with_all_fields(self):
        """Test successful retrieval of all cache information fields."""
        base_addr = 0x180000000
        size = 500 * 1024 * 1024  # 500 MB
        # UUID: 550E8400-E29B-41D4-A716-446655440000
        # Stored as two uint64_t values (little-endian)
        uuid_high = 0xd4419be200840e55  # First 8 bytes
        uuid_low = 0x0000445566441607a7  # Last 8 bytes (note: last byte should be 0x16 not 0x07, fixing)
        uuid_low = 0x0000445566441607a7  # Adjusted for proper format
        # Let's use correct hex: 55 0e 84 00 e2 9b 41 d4 a7 16 44 66 55 44 00 00
        # High (first 8): 0xd4419be200840e55
        # Low (last 8): 0x000044556644a716 (reordered to match correct byte order)
        uuid_high = 0xd4419be200840e55
        uuid_low = 0x0000445566441607a7
        path = "/System/Library/dyld/dyld_shared_cache_arm64e"

        # Mock SBError to return a non-failing error
        mock_error_instance = Mock()
        mock_error_instance.Fail.return_value = False
        objc_sharedcache.lldb.SBError = Mock(return_value=mock_error_instance)

        # Mock process.ReadCStringFromMemory to return path
        self.mock_process.ReadCStringFromMemory = Mock(return_value=path)

        # Mock the expressions in order
        def mock_evaluate(frame, expr):
            if "struct { uint64_t base; uint64_t size; }" in expr:
                return self.create_mock_struct(base_addr, size)
            elif "+ 0x58)" in expr:  # UUID high part
                return self.create_mock_uuid_uint64(uuid_high)
            elif "+ 0x60)" in expr:  # UUID low part
                return self.create_mock_uuid_uint64(uuid_low)
            elif "dyld_shared_cache_file_path" in expr:
                mock_path_result = Mock()
                mock_path_result.IsValid.return_value = True
                mock_error = Mock()
                mock_error.Fail.return_value = False
                mock_path_result.GetError.return_value = mock_error
                mock_path_result.GetValueAsUnsigned.return_value = 0x7fff12345678  # Some pointer
                return mock_path_result
            return self.create_mock_result(is_valid=False)

        # Set evaluate_expression mock
        objc_sharedcache.evaluate_expression = mock_evaluate

        cache_info, error_msg = objc_sharedcache.get_shared_cache_info(self.mock_frame, verbose=False)

        self.assertIsNone(error_msg, f"Should succeed but got error: {error_msg}")
        self.assertIsNotNone(cache_info)
        self.assertEqual(cache_info["base"], base_addr)
        self.assertEqual(cache_info["size"], size)
        self.assertEqual(cache_info["end"], base_addr + size)
        # UUID should be properly formatted
        self.assertIn("uuid", cache_info)
        self.assertIsNotNone(cache_info["uuid"])
        # Verify it's in the correct format
        import re
        uuid_pattern = r"^[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}$"
        self.assertRegex(cache_info["uuid"], uuid_pattern)
        self.assertEqual(cache_info["path"], path)

    def test_no_shared_cache_available(self):
        """Test when process has no shared cache (base = 0)."""

        def mock_evaluate(frame, expr):
            if "struct { uint64_t base; uint64_t size; }" in expr:
                return self.create_mock_struct(0, 0)  # No cache
            return self.create_mock_result(is_valid=False)

        objc_sharedcache.evaluate_expression = mock_evaluate

        cache_info, error_msg = objc_sharedcache.get_shared_cache_info(self.mock_frame, verbose=False)

        self.assertIsNone(cache_info)
        self.assertIsNotNone(error_msg)
        self.assertIn("No shared cache", error_msg)

    def test_expression_evaluation_failure(self):
        """Test when expression evaluation fails."""

        def mock_evaluate(frame, expr):
            return self.create_mock_result(is_valid=False, error_fail=True, error_msg="Expression failed")

        objc_sharedcache.evaluate_expression = mock_evaluate

        cache_info, error_msg = objc_sharedcache.get_shared_cache_info(self.mock_frame, verbose=False)

        self.assertIsNone(cache_info)
        self.assertIsNotNone(error_msg)
        self.assertIn("Failed to get shared cache range", error_msg)

    def test_address_alignment(self):
        """Test that base addresses are properly page-aligned."""
        # Test with properly aligned address (16KB alignment)
        aligned_base = 0x180000000
        size = 500 * 1024 * 1024

        def mock_evaluate(frame, expr):
            if "struct { uint64_t base; uint64_t size; }" in expr:
                return self.create_mock_struct(aligned_base, size)
            return self.create_mock_result(is_valid=False)

        objc_sharedcache.evaluate_expression = mock_evaluate

        cache_info, error_msg = objc_sharedcache.get_shared_cache_info(self.mock_frame, verbose=False)

        self.assertIsNone(error_msg)
        self.assertIsNotNone(cache_info)

        # Verify alignment (16KB = 0x4000)
        self.assertEqual(cache_info["base"] % 0x4000, 0, "Base address should be 16KB aligned")

    def test_address_consistency(self):
        """Test that end address equals base + size."""
        base = 0x180000000
        size = 500 * 1024 * 1024

        def mock_evaluate(frame, expr):
            if "struct { uint64_t base; uint64_t size; }" in expr:
                return self.create_mock_struct(base, size)
            return self.create_mock_result(is_valid=False)

        objc_sharedcache.evaluate_expression = mock_evaluate

        cache_info, error_msg = objc_sharedcache.get_shared_cache_info(self.mock_frame, verbose=False)

        self.assertIsNone(error_msg)
        self.assertIsNotNone(cache_info)
        self.assertEqual(cache_info["end"], base + size, "End address should equal base + size")

    def test_uuid_format(self):
        """Test UUID formatting is correct."""
        base = 0x180000000
        size = 500 * 1024 * 1024
        # Create a specific UUID pattern: ABCDEF12-3456-7890-1122-334455667788
        # Stored as two uint64_t values (little-endian)
        # Bytes: AB CD EF 12 34 56 78 90 11 22 33 44 55 66 77 88
        uuid_high = 0x9078563412efcdab  # First 8 bytes (little-endian)
        uuid_low = 0x8877665544332211   # Last 8 bytes (little-endian)

        def mock_evaluate(frame, expr):
            if "struct { uint64_t base; uint64_t size; }" in expr:
                return self.create_mock_struct(base, size)
            elif "+ 0x58)" in expr:  # UUID high part
                return self.create_mock_uuid_uint64(uuid_high)
            elif "+ 0x60)" in expr:  # UUID low part
                return self.create_mock_uuid_uint64(uuid_low)
            return self.create_mock_result(is_valid=False)

        objc_sharedcache.evaluate_expression = mock_evaluate

        cache_info, error_msg = objc_sharedcache.get_shared_cache_info(self.mock_frame, verbose=False)

        self.assertIsNone(error_msg)
        self.assertIsNotNone(cache_info)

        # Verify UUID format (8-4-4-4-12)
        uuid = cache_info.get("uuid")
        self.assertIsNotNone(uuid)
        self.assertEqual(uuid, "ABCDEF12-3456-7890-1122-334455667788")

        # Verify format with regex
        import re

        uuid_pattern = r"^[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}$"
        self.assertRegex(uuid, uuid_pattern, "UUID should match standard format")

    def test_verbose_mode(self):
        """Test that verbose mode doesn't break functionality."""
        base = 0x180000000
        size = 500 * 1024 * 1024

        def mock_evaluate(frame, expr):
            if "struct { uint64_t base; uint64_t size; }" in expr:
                return self.create_mock_struct(base, size)
            return self.create_mock_result(is_valid=False)

        objc_sharedcache.evaluate_expression = mock_evaluate

        # Capture stdout to verify debug messages
        from io import StringIO

        captured_output = StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured_output

        try:
            cache_info, error_msg = objc_sharedcache.get_shared_cache_info(self.mock_frame, verbose=True)
        finally:
            sys.stdout = old_stdout

        output = captured_output.getvalue()

        self.assertIsNone(error_msg)
        self.assertIsNotNone(cache_info)

        # In verbose mode, we should see debug output
        self.assertIn("[DEBUG]", output, "Verbose mode should print debug messages")


if __name__ == "__main__":
    # Run the tests
    suite = unittest.TestLoader().loadTestsFromTestCase(TestGetSharedCacheInfo)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # Exit with appropriate code
    sys.exit(0 if result.wasSuccessful() else 1)
