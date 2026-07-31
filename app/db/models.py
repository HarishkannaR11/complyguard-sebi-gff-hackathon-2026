from sqlalchemy import Column, String, Text, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship
import datetime

from app.db.database import Base


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


class Clause(Base):
    __tablename__ = "clauses"
    id = Column(String, primary_key=True)
    clause_number = Column(String)
    text = Column(Text)
    section_id = Column(String, ForeignKey("sections.id"))


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