"""Standalone test runner for the manufacturing demo (no pytest required).

    python3 demo/manufacturing/tests/run_tests.py
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import test_boundary  # noqa: E402,F401
import test_contract  # noqa: E402
import test_approval_integrity  # noqa: E402
import test_business_integrity  # noqa: E402
import test_cross_object_integrity  # noqa: E402


def main() -> int:
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromModule(test_boundary))
    suite.addTests(loader.loadTestsFromModule(test_contract))
    suite.addTests(loader.loadTestsFromModule(test_approval_integrity))
    suite.addTests(loader.loadTestsFromModule(test_business_integrity))
    suite.addTests(loader.loadTestsFromModule(test_cross_object_integrity))
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
