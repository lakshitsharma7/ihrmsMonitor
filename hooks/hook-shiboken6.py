"""Custom PyInstaller hook for shiboken6."""

from PyInstaller.utils.hooks import collect_all

datas, binaries, hiddenimports = collect_all("shiboken6")
