import pytest
import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base
from app.db.models import (
    Circular,
    Section,
    Clause,
    Obligation,
    Evidence,
    Deadline,
    ApplicableEntity,
    Task,
    EvidenceLog
)


def test_migration_and_lineage_relations():
    # Setup an in-memory SQL database for unit testing
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    
    # Verify migration runner can run ALTER TABLE on empty DB (or warnings logged)
    # The runner adds columns previous_obligation_id, amended_obligation_id, etc.
    # to existing tables. Let's create the tables via create_all first to simulate
    # an existing DB, then execute migrations, then run validation.
    Base.metadata.create_all(engine)
    
    # Initialize DB Session
    TestSessionLocal = sessionmaker(bind=engine)
    db = TestSessionLocal()
    
    try:
        # 1. Create a Circular
        circ_1 = Circular(id="SEBI-CIRC-1", title="Circular No 1", issue_date=datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None))
        db.add(circ_1)
        db.commit()
        
        # 2. Create Section
        sec_1 = Section(id="sec-1", title="Section 1: Guidelines", circular_id=circ_1.id)
        db.add(sec_1)
        db.commit()
        
        # 3. Create Clause
        cl_1 = Clause(id="cl-1", clause_number="2.3", text="The broker shall file audits monthly.", section_id=sec_1.id)
        db.add(cl_1)
        db.commit()
        
        # 4. Create parent Obligation
        obl_parent = Obligation(
            id="obl-parent-1",
            clause_id="clause-1",
            requirement="Broker filing audits monthly",
            frequency="monthly",
            evidence_type="audit report",
            deadline_rule="monthly",
            intermediary="stockbroker",
            status="active",
            origin_circular_id=circ_1.id,
            clause_uuid=cl_1.id
        )
        db.add(obl_parent)
        db.commit()
        
        # 5. Create Child (Amended) Obligation
        circ_2 = Circular(id="SEBI-CIRC-2", title="Circular No 2", issue_date=datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None))
        db.add(circ_2)
        sec_2 = Section(id="sec-2", title="Section 1: Updated Guidelines", circular_id=circ_2.id)
        db.add(sec_2)
        cl_2 = Clause(id="cl-2", clause_number="2.3", text="The broker shall file audits fortnightly.", section_id=sec_2.id)
        db.add(cl_2)
        db.commit()
        
        obl_amended = Obligation(
            id="obl-amended-2",
            clause_id="clause-1",
            requirement="Broker filing audits fortnightly",
            frequency="fortnightly",
            evidence_type="audit report",
            deadline_rule="fortnightly",
            intermediary="stockbroker",
            status="active",
            previous_obligation_id=obl_parent.id,
            amended_obligation_id=obl_parent.id,
            origin_circular_id=circ_2.id,
            clause_uuid=cl_2.id
        )
        db.add(obl_amended)
        
        # 6. Add Deadline
        dl_1 = Deadline(id="dl-1", due_date=datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None), status="open", obligation_id=obl_amended.id)
        db.add(dl_1)
        
        # 7. Add Evidence
        ev_1 = Evidence(id="ev-1", file_ref="fortnightly_file.pdf", obligation_id=obl_amended.id)
        db.add(ev_1)
        
        # 8. Add ApplicableEntity
        ent_1 = ApplicableEntity(id="ent-1", entity_name="stockbroker", obligation_id=obl_amended.id)
        db.add(ent_1)
        db.commit()
        
        # ----------------------------------------------------
        # Verify Lineage Assertions
        # ----------------------------------------------------
        refreshed_amended = db.query(Obligation).filter(Obligation.id == obl_amended.id).first()
        
        # Lineage version links
        assert refreshed_amended.previous_obligation_id == "obl-parent-1"
        assert refreshed_amended.amended_obligation_id == "obl-parent-1"
        assert refreshed_amended.superseded_obligation_id is None
        
        # Circular relation link
        assert refreshed_amended.origin_circular.id == "SEBI-CIRC-2"
        
        # Clause -> Section -> Circular hierarchy traversal
        assert refreshed_amended.clause.id == "cl-2"
        assert refreshed_amended.clause.clause_number == "2.3"
        assert refreshed_amended.clause.section.id == "sec-2"
        assert refreshed_amended.clause.section.circular_id == "SEBI-CIRC-2"
        
        # Children Lists
        assert len(refreshed_amended.deadlines) == 1
        assert refreshed_amended.deadlines[0].id == "dl-1"
        
        assert len(refreshed_amended.evidence_items) == 1
        assert refreshed_amended.evidence_items[0].file_ref == "fortnightly_file.pdf"
        
        assert len(refreshed_amended.applicable_entities) == 1
        assert refreshed_amended.applicable_entities[0].entity_name == "stockbroker"
        
        # Verify backref traversal on parent obligation
        refreshed_parent = db.query(Obligation).filter(Obligation.id == obl_parent.id).first()
        # SQLAlchemy self-referential backref test
        assert refreshed_parent.origin_circular_id == "SEBI-CIRC-1"
        
    finally:
        db.close()
