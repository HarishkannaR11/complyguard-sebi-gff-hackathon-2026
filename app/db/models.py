from sqlalchemy import Column, String, Text, DateTime, ForeignKey, JSON
import datetime

from app.db.database import Base

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