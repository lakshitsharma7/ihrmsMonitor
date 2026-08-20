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

    engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    yield factory

    engine.dispose()
    os.unlink(path)
