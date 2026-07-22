import os
import tempfile
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

# Setup test DB before importing main
TEST_DB_PATH = Path(tempfile.gettempdir()) / f"adam_ai_pytest_{uuid.uuid4().hex}.db"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH.as_posix()}"
os.environ["ENV"] = "test"
os.environ["JWT_SECRET"] = "super-secret-test-key-32-chars-long"
os.environ["NODE_INTERNAL_SECRET"] = "secret"
# Legacy-route regression tests choose the explicit V1 rollback. V2/default
# tests override this single canonical control per case.
os.environ["PUBLIC_WEB_CHAT_RESPONSE_ENGINE"] = "v1"
# Most existing /chat and Meta tests are rollback-regression coverage for
# brain.py. Dedicated V2 channel tests override this explicitly.
os.environ["WHATSAPP_RESPONSE_ENGINE"] = "v1"
os.environ["EXTERNAL_API_RESPONSE_ENGINE"] = "v1"

from database import Base, get_db
from main import app

engine = create_engine(os.environ["DATABASE_URL"], connect_args={"check_same_thread": False})


@event.listens_for(engine, "connect")
def _enable_sqlite_integrity(dbapi_connection, _connection_record):
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
    finally:
        cursor.close()


TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

import database
import brain
import services.context_engine
import services.processing_claim
import routers.webhook

database.SessionLocal = TestingSessionLocal
brain.SessionLocal = TestingSessionLocal
services.context_engine.SessionLocal = TestingSessionLocal
services.processing_claim.SessionLocal = TestingSessionLocal
routers.webhook.SessionLocal = TestingSessionLocal


@pytest.fixture(scope="session", autouse=True)
def setup_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)
    engine.dispose()
    if TEST_DB_PATH.exists():
        try:
            TEST_DB_PATH.unlink()
        except PermissionError:
            pass


@pytest.fixture
def db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    try:
        from main import limiter
        import rate_limiter as public_rate_limiter
        if hasattr(limiter, "_limiter") and hasattr(limiter._limiter, "storage"):
            limiter._limiter.storage.reset()
        public_rate_limiter._reset_local_rate_limits_for_tests()
    except Exception:
        pass
    yield
    try:
        import rate_limiter as public_rate_limiter
        public_rate_limiter._reset_local_rate_limits_for_tests()
    except Exception:
        pass


@pytest.fixture
def client(db):
    def override_get_db():
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
