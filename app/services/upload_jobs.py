"""Persistence and background runner for upload jobs."""
import datetime
import logging
import uuid

from sqlalchemy.orm import Session

from app.db.models import UploadJob
from app.services.upload_pipeline import process_chunks

logger = logging.getLogger(__name__)

QUEUED, RUNNING, COMPLETED, FAILED = "queued", "running", "completed", "failed"


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


def create_job(db: Session, *, filename: str, circular_id: str, total: int) -> UploadJob:
    job = UploadJob(
        id=str(uuid.uuid4()), filename=filename, circular_id=circular_id,
        status=QUEUED, total_clauses=total, processed_clauses=0,
        created_at=_now(), updated_at=_now(),
    )
    db.add(job)
    db.commit()
    return job


def job_to_dict(job: UploadJob) -> dict:
    return {
        "job_id": job.id,
        "status": job.status,
        "filename": job.filename,
        "circular_id": job.circular_id,
        "clauses_total": job.total_clauses,
        "clauses_done": job.processed_clauses,
        "result": job.result,
        "error": job.error,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
    }


def run_job(session_factory, job_id: str, filename: str, circular_id: str, chunks: list[dict]) -> None:
    """Background entry point. Owns its own DB session; never raises."""
    db = session_factory()
    try:
        job = db.get(UploadJob, job_id)
        job.status = RUNNING
        job.updated_at = _now()
        db.commit()

        def on_progress(done: int, total: int) -> None:
            job.processed_clauses = done
            job.updated_at = _now()
            db.commit()

        result = process_chunks(
            db, filename=filename, circular_id=circular_id, chunks=chunks, on_progress=on_progress
        )
        job.status = COMPLETED
        job.result = result
        job.updated_at = _now()
        db.commit()
    except Exception as exc:
        logger.exception("Upload job %s failed", job_id)
        db.rollback()
        try:
            job = db.get(UploadJob, job_id)
            job.status = FAILED
            job.error = str(exc)
            job.updated_at = _now()
            db.commit()
        except Exception:
            logger.exception("Could not record failure of upload job %s", job_id)
    finally:
        db.close()


def fail_interrupted_jobs(session_factory) -> int:
    """On startup, jobs still queued/running were killed by a restart; mark them failed."""
    db = session_factory()
    try:
        stale = db.query(UploadJob).filter(UploadJob.status.in_([QUEUED, RUNNING])).all()
        for job in stale:
            job.status = FAILED
            job.error = "Interrupted by a server restart; please upload again."
            job.updated_at = _now()
        db.commit()
        return len(stale)
    except Exception:
        db.rollback()
        logger.exception("Could not clean up interrupted upload jobs")
        return 0
    finally:
        db.close()
