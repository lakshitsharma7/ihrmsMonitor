"""Runtime hook for PySide6 to ensure DLL directory and shiboken6 / PySide6 resolution succeeds in PyInstaller on Windows."""

import os
import sys
from pathlib import Path

try:
    if sys.platform.startswith("win") and getattr(sys, "frozen", False):
        base_dir = Path(getattr(sys, "_MEIPASS", os.path.dirname(sys.executable)))
        shiboken_dir = base_dir / "shiboken6"
        pyside_dir = base_dir / "PySide6"

        for p in (base_dir, shiboken_dir, pyside_dir):
            if p.is_dir():
                p_str = str(p)
                if p_str not in sys.path:
                    sys.path.insert(0, p_str)
                try:
                    os.add_dll_directory(p_str)
                except Exception:
                    pass
                os.environ["PATH"] = p_str + os.pathsep + os.environ.get("PATH", "")

        try:
            import shiboken6
            if shiboken_dir.is_dir() and str(shiboken_dir) not in shiboken6.__path__:
                shiboken6.__path__.insert(0, str(shiboken_dir))
            if str(base_dir) not in shiboken6.__path__:
                shiboken6.__path__.append(str(base_dir))
        except Exception:
            pass

        try:
            import PySide6
            if pyside_dir.is_dir() and str(pyside_dir) not in PySide6.__path__:
                PySide6.__path__.insert(0, str(pyside_dir))
            if str(base_dir) not in PySide6.__path__:
                PySide6.__path__.append(str(base_dir))
        except Exception:
            pass

        # Ensure Qt platform and imageformat plugin paths are correctly resolved
        plugins_candidates = [
            pyside_dir / "plugins",
            base_dir / "plugins",
            base_dir / "PySide6" / "plugins",
        ]
        for pl_dir in plugins_candidates:
            if pl_dir.is_dir():
                os.environ["QT_PLUGIN_PATH"] = str(pl_dir)
                platforms_dir = pl_dir / "platforms"
                if platforms_dir.is_dir():
                    os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = str(platforms_dir)
                break

        # High-DPI and stable rendering environment variables
        os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
        os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")

        # Clean any invalid CA bundle environment variables from previous sessions / other machines
        for env_var in ("REQUESTS_CA_BUNDLE", "SSL_CERT_FILE", "CURL_CA_BUNDLE"):
            val = os.environ.get(env_var)
            if val and not os.path.isfile(val):
                os.environ.pop(env_var, None)

        # Remove conflicting global python environment variables that disrupt embedded interpreter
        for py_env in ("PYTHONHOME", "PYTHONPATH"):
            os.environ.pop(py_env, None)

        # Resolve bundled TLS CA certificate bundle dynamically
        exe_dir = Path(sys.executable).parent
        ca_candidates = [
            base_dir / "certifi" / "cacert.pem",
            base_dir / "cacert.pem",
            exe_dir / "_internal" / "certifi" / "cacert.pem",
            exe_dir / "_internal" / "cacert.pem",
            exe_dir / "certifi" / "cacert.pem",
            exe_dir / "cacert.pem",
        ]
        for ca_cand in ca_candidates:
            if ca_cand.is_file():
                ca_str = str(ca_cand)
                os.environ["REQUESTS_CA_BUNDLE"] = ca_str
                os.environ["SSL_CERT_FILE"] = ca_str
                try:
                    import certifi
                    certifi.where = lambda: ca_str
                    if hasattr(certifi, "core"):
                        certifi.core.where = lambda: ca_str
                except Exception:
                    pass
                break
except Exception:
    pass

