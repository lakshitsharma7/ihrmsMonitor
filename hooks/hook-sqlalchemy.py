"""Custom PyInstaller hook for SQLAlchemy 2.0 to avoid legacy 'sqlalchemy.databases' lookup."""

from PyInstaller.utils.hooks import collect_submodules

hiddenimports = collect_submodules("sqlalchemy.dialects.sqlite") + collect_submodules("sqlalchemy.orm") + [
    "sqlalchemy.sql.default_comparator",
]
