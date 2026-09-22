"""Cross-platform test runner for Workpulse CI and local execution.

Executes all discovered unit and integration tests and terminates cleanly with
os._exit() to prevent PySide6/Qt thread teardown deadlocks on macOS/Linux.
"""

from __future__ import annotations

import os
import sys
import unittest


def main() -> None:
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if root_dir not in sys.path:
        sys.path.insert(0, root_dir)

    loader = unittest.defaultTestLoader
    start_dir = os.path.join(root_dir, "tests")
    suite = loader.discover(start_dir, top_level_dir=root_dir)
    runner = unittest.TextTestRunner(verbosity=1)
    result = runner.run(suite)
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0 if result.wasSuccessful() else 1)


if __name__ == "__main__":
    main()
