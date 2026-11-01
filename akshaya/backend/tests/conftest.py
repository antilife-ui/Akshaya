import os
import tempfile

# Must be set before the app is imported so tests use a throw-away database.
_tmp = tempfile.mkdtemp(prefix="akshaya_test_")
os.environ["AKSHAYA_DB_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["AKSHAYA_ENABLE_SCHEDULER"] = "0"

import pytest  # noqa: E402


def _fresh_client():
    pytest.importorskip("fastapi")
    pytest.importorskip("sqlalchemy")
    pytest.importorskip("statsmodels")
    from fastapi.testclient import TestClient

    from app.database import Base, engine
    from app.main import app

    Base.metadata.drop_all(engine)
    return TestClient(app)


@pytest.fixture()
def client():
    with _fresh_client() as c:  # lifespan creates tables + default materials
        yield c


@pytest.fixture(scope="module")
def seeded():
    with _fresh_client() as c:
        r = c.post("/api/v1/simulation/seed", json={"confirm": True})
        assert r.status_code == 200, r.text
        yield c
