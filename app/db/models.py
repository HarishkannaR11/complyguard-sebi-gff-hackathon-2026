from sqlalchemy import Column, String, Text, DateTime, ForeignKey, JSON, Float, Integer
from sqlalchemy.orm import relationship
import datetime

from app.db.database import Base

# Sentinel values for source_type on Obligation
SOURCE_REGULATORY = "regulatory"
SOURCE_COMPANY = "company"


class Circular(Base):
    __tablename__ = "circulars"
    id = Column(String, primary_key=True)
    title = Column(String, nullable=True)
    issue_date = Column(DateTime, default=datetime.datetime.utcnow)


class Section(Base):
    __tablename__ = "sections"
    id = Column(String, primary_key=True)
    title = Column(String)
    circular_id = Column(String, ForeignKey("circulars.id"))
    
    circular = relationship("Circular")


class Clause(Base):
    __tablename__ = "clauses"
    id = Column(String, primary_key=True)
    clause_number = Column(String)
    text = Column(Text)
    section_id = Column(String, ForeignKey("sections.id"))

    section = relationship("Section")


class Obligation(Base):
    __tablename__ = "obligations"
    id = Column(String, primary_key=True)
    clause_id = Column(String)
    requirement = Column(Text)
    frequency = Column(String)
    evidence_type = Column(String)
    deadline_rule = Column(String)
    intermediary = Column(String, default="stockbroker")
    status = Column(String, default="active")
    # Discriminator: 'regulatory' = extracted from SEBI circular
    #                'company'    = imported from company CSV
    source_type = Column(String, default=SOURCE_REGULATORY)

    # Lineage fields (V2 Upgrade)
    previous_obligation_id = Column(String, ForeignKey("obligations.id"), nullable=True)
    amended_obligation_id = Column(String, ForeignKey("obligations.id"), nullable=True)
    superseded_obligation_id = Column(String, ForeignKey("obligations.id"), nullable=True)
    origin_circular_id = Column(String, ForeignKey("circulars.id"), nullable=True)
    clause_uuid = Column(String, ForeignKey("clauses.id"), nullable=True)

    # Relationships
    previous_obligation = relationship(
        "Obligation", remote_side=[id], foreign_keys=[previous_obligation_id]
    )
    amended_obligation = relationship(
        "Obligation", remote_side=[id], foreign_keys=[amended_obligation_id]
    )
    superseded_obligation = relationship(
        "Obligation", remote_side=[id], foreign_keys=[superseded_obligation_id]
    )
    origin_circular = relationship("Circular")
    clause = relationship("Clause")

    evidence_items = relationship("Evidence", back_populates="obligation")
    deadlines = relationship("Deadline", back_populates="obligation")
    applicable_entities = relationship("ApplicableEntity", back_populates="obligation")


class Evidence(Base):
    __tablename__ = "evidence"
    id = Column(String, primary_key=True)
    file_ref = Column(String)
    submitted_at = Column(DateTime, default=datetime.datetime.utcnow)
    obligation_id = Column(String, ForeignKey("obligations.id"))

    obligation = relationship("Obligation", back_populates="evidence_items")


class Deadline(Base):
    __tablename__ = "deadlines"
    id = Column(String, primary_key=True)
    due_date = Column(DateTime)
    status = Column(String, default="open")
    obligation_id = Column(String, ForeignKey("obligations.id"))

    obligation = relationship("Obligation", back_populates="deadlines")


class ApplicableEntity(Base):
    __tablename__ = "applicable_entities"
    id = Column(String, primary_key=True)
    entity_name = Column(String)
    obligation_id = Column(String, ForeignKey("obligations.id"))

    obligation = relationship("Obligation", back_populates="applicable_entities")


# Existing Task and EvidenceLog for backwards compatibility
class Task(Base):
    __tablename__ = "tasks"
    id = Column(String, primary_key=True)
    obligation_id = Column(String, ForeignKey("obligations.id"))
    owner = Column(String)
    due_date = Column(DateTime)
    status = Column(String, default="open")


class EvidenceLog(Base):
    __tablename__ = "evidence_log"
    id = Column(String, primary_key=True)
    task_id = Column(String, ForeignKey("tasks.id"))
    file_ref = Column(String)
    submitted_at = Column(DateTime, default=datetime.datetime.utcnow)


class AuditTrail(Base):
    __tablename__ = "audit_trail"
    id = Column(String, primary_key=True)
    thread_id = Column(String)
    node_name = Column(String)
    action = Column(JSON)
    actor = Column(String)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)
    prev_hash = Column(String)
    hash = Column(String)


class ReviewQueue(Base):
    __tablename__ = "review_queue"
    id = Column(String, primary_key=True)  # thread_id
    circular_id = Column(String)
    clause_id = Column(String)
    previous_clause = Column(Text, nullable=True)
    new_clause = Column(Text)
    highlighted_diff = Column(Text, nullable=True)
    llm_explanation = Column(Text, nullable=True)
    confidence = Column(Float, nullable=True)
    extracted_obligation = Column(JSON, nullable=True)
    status = Column(String, default="pending")


class CompanyObligation(Base):
    """Company-side obligations imported from CSV."""
    __tablename__ = "company_obligations"
    id = Column(String, primary_key=True)
    requirement = Column(Text)
    frequency = Column(String)
    evidence_type = Column(String)
    deadline_rule = Column(String, nullable=True)
    intermediary = Column(String, default="stockbroker")
    owner = Column(String, default="compliance")
    due_date = Column(DateTime, nullable=True)
    status = Column(String, default="open")  # open / met
    imported_at = Column(DateTime, default=datetime.datetime.utcnow)
    source_file = Column(String, nullable=True)


class GapResult(Base):
    """Results of a Gap Engine run comparing regulatory vs company obligations."""
    __tablename__ = "gap_results"
    id = Column(String, primary_key=True)
    regulatory_obligation_id = Column(String, nullable=True)
    company_obligation_id = Column(String, nullable=True)
    # gap_type: 'missing' | 'modified' | 'extra' | 'met'
    gap_type = Column(String)
    detail = Column(Text, nullable=True)
    computed_at = Column(DateTime, default=datetime.datetime.utcnow)


class WorkflowStateRecord(Base):
    """Single-row table holding the current workflow state (id='current')."""
    __tablename__ = "workflow_state"
    id = Column(String, primary_key=True, default="current")
    state = Column(String, default="IDLE")
    updated_at = Column(DateTime, default=datetime.datetime.utcnow)

class UploadJob(Base):
    """Background run of the per-clause pipeline for one uploaded circular."""
    __tablename__ = "upload_jobs"
    id = Column(String, primary_key=True)
    filename = Column(String)
    circular_id = Column(String)
    # queued | running | completed | failed
    status = Column(String, default="queued")
    total_clauses = Column(Integer, default=0)
    processed_clauses = Column(Integer, default=0)
    result = Column(JSON, nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow)
