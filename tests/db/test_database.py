
from app.db.database import make_engine


def test_make_engine_uses_provided_url():
    engine = make_engine("sqlite:///:memory:")
    assert engine.url.drivername == "sqlite"
    assert engine.url.database == ":memory:"


def test_make_engine_defaults_to_env_var(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./test_default.db")
    engine = make_engine()
    assert "test_default.db" in str(engine.url)
