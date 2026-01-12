                            /Library/Frameworks/Python.framework/Versions/3.11/bin/python3 ./tests/run_all_tests.py --quick

======================================================================
test session starts
platform darwin -- Python 3.11.6
collected 3 test suites

.F. [100%]

======================================================================
FAILURES
======================================================================

______________________________________________________________________
hierarchy :: Class hierarchy display
Result: 2/7 passed (47.04s)
______________________________________________________________________

  Few Matches (NSMutable*)

  Expected compact hierarchy for few matches
    Expected: 'Found N' count with hierarchy arrows
        Actual: Match count or hierarchy not detected
        Output preview: TIMEOUT waiting for command: ocls NSMutable*
      Output (first 500 chars):
      TIMEOUT waiting for command: ocls NSMutable*

  Each class shows hierarchy (2-20)

  Could not parse match count
    Expected: 'Found N' in output
        Actual: Match count format not recognized
        Output preview:  breakpoint delete -f
    error: No breakpoints exist to be deleted.
      Output (first 500 chars):
       breakpoint delete -f
    error: No breakpoints exist to be deleted.

  Many Matches (NS*) - no per-class hierarchy

  ... and 5 more failures

  Re-run this suite: ./tests/test_hierarchy.py
  Re-run this suite: python3 tests/test_hierarchy.py

======================================================================
1 failed, 2 passed in 90.86s
(5 failed, 32 passed tests total)
======================================================================
alan@MacBookPro lldb-objc % 