"""Generate Windows file_version_info.txt for PyInstaller from config.settings.APP_VERSION."""

import os
import re
import sys
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import APP_VERSION, APP_NAME


def parse_version_tuple(v_str: str) -> tuple[int, int, int, int]:
    """Parse version string into a 4-tuple of integers for Windows PE version info."""
    clean = re.sub(r"[^\d.]", "", v_str).strip(".")
    parts = [int(p) for p in clean.split(".") if p.isdigit()]
    while len(parts) < 4:
        parts.append(0)
    return tuple(parts[:4])  # type: ignore


def generate_version_info(target_file: str = "file_version_info.txt", version_str: str | None = None) -> str:
    ver = version_str or str(APP_VERSION)
    v_tuple = parse_version_tuple(ver)
    v_str = f"{v_tuple[0]}.{v_tuple[1]}.{v_tuple[2]}.{v_tuple[3]}"

    content = f"""# UTF-8
#
# Version Information file for PyInstaller
#
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={v_tuple},
    prodvers={v_tuple},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo(
      [
        StringTable(
          '040904B0',
          [
            StringStruct('CompanyName', 'Indovision Services'),
            StringStruct('FileDescription', '{APP_NAME} Desktop Client'),
            StringStruct('FileVersion', '{v_str}'),
            StringStruct('InternalName', 'iHRMS-Desktop'),
            StringStruct('LegalCopyright', 'Copyright (C) Indovision Services'),
            StringStruct('OriginalFilename', 'iHRMS-Desktop.exe'),
            StringStruct('ProductName', '{APP_NAME}'),
            StringStruct('ProductVersion', '{v_str}')
          ]
        )
      ]
    ),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""
    out_path = PROJECT_ROOT / target_file
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"Generated {out_path} for version {ver} ({v_str})")

    # Also generate supervisor version info
    sup_content = f"""# UTF-8
#
# Version Information file for PyInstaller - {APP_NAME} Supervisor
#
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={v_tuple},
    prodvers={v_tuple},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo(
      [
        StringTable(
          '040904B0',
          [
            StringStruct('CompanyName', 'Indovision Services'),
            StringStruct('FileDescription', '{APP_NAME} Supervisor'),
            StringStruct('FileVersion', '{v_str}'),
            StringStruct('InternalName', 'iHRMS-Supervisor'),
            StringStruct('LegalCopyright', 'Copyright (C) Indovision Services'),
            StringStruct('OriginalFilename', 'iHRMS-Supervisor.exe'),
            StringStruct('ProductName', '{APP_NAME} Supervisor'),
            StringStruct('ProductVersion', '{v_str}')
          ]
        )
      ]
    ),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""
    sup_path = PROJECT_ROOT / "file_version_info_supervisor.txt"
    with open(sup_path, "w", encoding="utf-8") as f:
        f.write(sup_content)
    print(f"Generated {sup_path} for version {ver} ({v_str})")
    return str(out_path)


if __name__ == "__main__":
    cli_ver = sys.argv[1] if len(sys.argv) > 1 else None
    generate_version_info(version_str=cli_ver)
