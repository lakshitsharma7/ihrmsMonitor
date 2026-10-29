"""Shared pytest fixtures.

All shared business logic (tracker, repository, services) can be tested
against a throwaway SQLite file with no GUI and no OS-specific code
involved, per the spec's testing requirements.
"""

from __future__ import annotations

import os
import tempfile

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database.models import Base


@pytest.fixture()
def session_factory():
    """Yield a SQLAlchemy session factory backed by a temp SQLite file."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    from sqlalchemy.pool import NullPool

    engine = create_engine(
        f"sqlite:///{path}",
        connect_args={"check_same_thread": False},
        poolclass=NullPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    yield factory

    try:
        engine.dispose()
    except Exception:
        pass

    try:
        if os.path.exists(path):
            os.unlink(path)
    except Exception:
        pass

@pytest.fixture(autouse=True)
def guard_network_calls(monkeypatch):
    """Enforce a strict timeout on unmocked HTTP network requests in tests to prevent runner hangs."""
    try:
        import requests
        orig_send = requests.Session.send

        def safe_send(session, request, **kwargs):
            if not kwargs.get("timeout") or kwargs.get("timeout") > 3.0:
                kwargs["timeout"] = 3.0
            return orig_send(session, request, **kwargs)

        monkeypatch.setattr(requests.Session, "send", safe_send)
    except Exception:
        pass


@pytest.fixture(autouse=True)
def cleanup_qt_windows():
    """Ensure top-level Qt widgets and their worker threads are cleanly stopped after each test."""
    yield
    try:
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app:
            for widget in list(app.topLevelWidgets()):
                if hasattr(widget, "_really_quit"):
                    widget._really_quit = True
                if hasattr(widget, "_shutdown"):
                    try:
                        widget._shutdown()
                    except Exception:
                        pass
                try:
                    widget.close()
                except Exception:
                    pass
    except Exception:
        pass
