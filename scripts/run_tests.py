"""Cross-platform test runner for iHRMS Desktop CI and local execution.

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

    try:
        import pytest
        args = [os.path.join(root_dir, "tests"), "-q"]
        try:
            import pytest_timeout  # type: ignore # noqa: F401
            args += ["--timeout=120", "--timeout-method=thread"]
        except ImportError:
            pass
        if sys.platform == "darwin":
            # Skip Windows-only test files entirely to prevent background threads hanging CI
            macos_ignore = [
                "--ignore", os.path.join(root_dir, "tests", "test_background_mode_and_sync_reliability.py"),
                "--ignore", os.path.join(root_dir, "tests", "test_background_mode_and_visibility.py"),
                "--ignore", os.path.join(root_dir, "tests", "test_windows_lock_and_display_off.py"),
                "--ignore", os.path.join(root_dir, "tests", "test_uninstall_detection.py"),
            ]
            args += macos_ignore
        exit_code = pytest.main(args)
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(exit_code)
    except ImportError:
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

