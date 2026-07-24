"""Seeds the database with initial synthetic compliance obligations, tasks, and audit logs."""
from dotenv import load_dotenv
load_dotenv()

import uuid
import datetime
from app.db.database import SessionLocal, Base, engine
from app.db.models import Obligation, Task, EvidenceLog, AuditTrail
from app.graph.nodes import compute_audit_hash

def seed() -> None:
    # Ensure tables exist
    Base.metadata.create_all(bind=engine)
    
    db = SessionLocal()
    try:
        # Check if already seeded
        if db.query(Obligation).first() is not None:
            print("Database already seeded. Skipping.")
            return

        print("Seeding synthetic data...")

        # 1. Obligations
        ob1 = Obligation(
            id="ob-networth",
            clause_id="clause-networth-1.1",
            requirement="Intermediary Stock Broker must maintain a minimum net worth of Rs. 1 Crore and submit the annual certificate.",
            frequency="annual",
            evidence_type="Networth Certificate PDF signed by CA",
            deadline_rule="annual",
            intermediary="stockbroker",
            status="active"
        )
        ob2 = Obligation(
            id="ob-audit",
            clause_id="clause-audit-2.4",
            requirement="Submit half-yearly internal systems audit report to SEBI through the online portal.",
            frequency="half-yearly",
            evidence_type="Internal Audit Report PDF",
            deadline_rule="180",
            intermediary="investment_adviser",
            status="active"
        )
        ob3 = Obligation(
            id="ob-collateral",
            clause_id="clause-collateral-3.2",
            requirement="Establish segregation and monitoring processes for client collaterals and report daily collateral status.",
            frequency="daily",
            evidence_type="Daily reporting CSV log",
            deadline_rule="daily",
            intermediary="depository",
            status="active"
        )
        ob4 = Obligation(
            id="ob-portfolio",
            clause_id="clause-portfolio-4.1",
            requirement="Submit monthly portfolio holdings disclosure of all mutual fund schemes to the public website.",
            frequency="monthly",
            evidence_type="Portfolio Disclosure URL / PDF",
            deadline_rule="monthly",
            intermediary="asset_management_company",
            status="active"
        )
        ob5 = Obligation(
            id="ob-rta-grievance",
            clause_id="clause-rta-5.5",
            requirement="Maintain grievance redressal registers and submit quarterly status updates to SEBI.",
            frequency="quarterly",
            evidence_type="Quarterly Grievance Report PDF",
            deadline_rule="quarterly",
            intermediary="registrar_and_transfer_agent",
            status="active"
        )
        ob6 = Obligation(
            id="ob-mii-bcp",
            clause_id="clause-mii-6.1",
            requirement="Perform half-yearly Disaster Recovery and Business Continuity Plan (BCP) drills and submit the audit report.",
            frequency="half-yearly",
            evidence_type="BCP Drill Audit Report PDF",
            deadline_rule="180",
            intermediary="market_infrastructure_institution",
            status="active"
        )
        db.add_all([ob1, ob2, ob3, ob4, ob5, ob6])
        db.flush()

        # 2. Tasks
        task1 = Task(
            id="task-networth",
            obligation_id="ob-networth",
            owner="finance",
            due_date=datetime.datetime.utcnow() + datetime.timedelta(days=30),
            status="open"
        )
        task2 = Task(
            id="task-audit",
            obligation_id="ob-audit",
            owner="compliance",
            due_date=datetime.datetime.utcnow() - datetime.timedelta(days=15),
            status="open"
        )
        task3 = Task(
            id="task-collateral",
            obligation_id="ob-collateral",
            owner="risk_team",
            due_date=datetime.datetime.utcnow() - datetime.timedelta(days=1),
            status="met"
        )
        task4 = Task(
            id="task-portfolio",
            obligation_id="ob-portfolio",
            owner="portfolio_ops",
            due_date=datetime.datetime.utcnow() + datetime.timedelta(days=5),
            status="open"
        )
        task5 = Task(
            id="task-rta-grievance",
            obligation_id="ob-rta-grievance",
            owner="rta_compliance",
            due_date=datetime.datetime.utcnow() + datetime.timedelta(days=20),
            status="open"
        )
        task6 = Task(
            id="task-mii-bcp",
            obligation_id="ob-mii-bcp",
            owner="dr_ops",
            due_date=datetime.datetime.utcnow() + datetime.timedelta(days=45),
            status="open"
        )
        db.add_all([task1, task2, task3, task4, task5, task6])
        db.flush()

        # 3. Evidence Log for completed task
        ev = EvidenceLog(
            id="evidence-collateral-1",
            task_id="task-collateral",
            file_ref="daily_collateral_system_log_2026-07-23.csv",
            submitted_at=datetime.datetime.utcnow() - datetime.timedelta(days=1, hours=2)
        )
        db.add(ev)

        # 4. Audit Trail Hash Chain
        # Entry 1: Seeding Obligations
        action1 = {"action": "seed_obligations", "count": 6}
        ts1 = datetime.datetime.utcnow() - datetime.timedelta(days=2)
        hash1 = compute_audit_hash("", action1, ts1)
        
        audit1 = AuditTrail(
            id=str(uuid.uuid4()),
            thread_id="seed:obligations",
            node_name="finalize",
            action=action1,
            actor="system",
            timestamp=ts1,
            prev_hash="",
            hash=hash1
        )
        
        # Entry 2: Seeding Tasks & Evidence
        action2 = {"action": "seed_evidence", "task_id": "task-collateral"}
        ts2 = datetime.datetime.utcnow() - datetime.timedelta(days=1)
        hash2 = compute_audit_hash(hash1, action2, ts2)
        
        audit2 = AuditTrail(
            id=str(uuid.uuid4()),
            thread_id="seed:evidence",
            node_name="finalize",
            action=action2,
            actor="system",
            timestamp=ts2,
            prev_hash=hash1,
            hash=hash2
        )
        db.add_all([audit1, audit2])

        db.commit()
        print("Successfully seeded database with synthetic data.")
    except Exception as exc:
        db.rollback()
        print(f"Error seeding data: {exc}")
    finally:
        db.close()

if __name__ == "__main__":
    seed()
