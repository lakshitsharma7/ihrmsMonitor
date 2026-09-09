"""Runtime hook for PySide6 to ensure DLL directory and shiboken6 / PySide6 resolution succeeds in PyInstaller onedir/onefile mode on Windows."""

import os
import sys
from pathlib import Path

if sys.platform.startswith("win") and getattr(sys, "frozen", False):
    base_dir = Path(getattr(sys, "_MEIPASS", os.path.dirname(sys.executable)))
    shiboken_dir = base_dir / "shiboken6"
    shiboken_dir.mkdir(parents=True, exist_ok=True)
    pyside_dir = base_dir / "PySide6"
    pyside_dir.mkdir(parents=True, exist_ok=True)

    # Add to sys.path if not present
    for p in (base_dir, shiboken_dir, pyside_dir):
        p_str = str(p)
        if p_str not in sys.path:
            sys.path.insert(0, p_str)
        try:
            os.add_dll_directory(p_str)
        except Exception:
            pass
        os.environ["PATH"] = p_str + os.pathsep + os.environ.get("PATH", "")

    # Ensure shiboken6 and PySide6 packages have their filesystem directories in __path__
    try:
        import shiboken6
        if str(shiboken_dir) not in shiboken6.__path__:
            shiboken6.__path__.insert(0, str(shiboken_dir))
        if str(base_dir) not in shiboken6.__path__:
            shiboken6.__path__.append(str(base_dir))
    except Exception:
        pass

    try:
        import PySide6
        if str(pyside_dir) not in PySide6.__path__:
            PySide6.__path__.insert(0, str(pyside_dir))
        if str(base_dir) not in PySide6.__path__:
            PySide6.__path__.append(str(base_dir))
    except Exception:
        pass
