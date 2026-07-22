import os
import pytest
from sqlalchemy import create_engine
from database import resolve_database_url

def test_sqlite_pool_bounds_enforced(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///test_pool_bounds.db")
    monkeypatch.setenv("SQLITE_POOL_SIZE", "150")
    monkeypatch.setenv("SQLITE_MAX_OVERFLOW", "50")
    
    with pytest.raises(ValueError, match="SQLITE_POOL_SIZE cannot exceed 100"):
        # Import database within the test to trigger engine creation with the monkeypatched env vars
        import importlib
        import database
        importlib.reload(database)
