from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.db.models import UploadJob
from app.services.upload_jobs import create_job, job_to_dict


def test_create_job_leaves_no_transaction_open():
    """A transaction left open by the request session blocks LangGraph's
    CREATE INDEX CONCURRENTLY in the background job (seen against real Postgres)."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    db = factory()

    job_id = create_job(db, filename="a.pdf", circular_id="a", total=3)

    assert isinstance(job_id, str)
    assert not db.in_transaction()
    fresh = factory()
    assert job_to_dict(fresh.get(UploadJob, job_id))["status"] == "queued"
