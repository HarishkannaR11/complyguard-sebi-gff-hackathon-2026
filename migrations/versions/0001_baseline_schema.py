"""baseline schema

Snapshot of the schema as of the move to Alembic. It is safe to run against a database
that was created by ``Base.metadata.create_all`` plus the retired ``migrate_v2`` /
``migrate_v3`` scripts: tables that already exist are left alone and the obligation
columns those scripts used to add are added only if missing.

Revision ID: 0001
Revises: 
Create Date: 2026-10-17 17:52:40.257294
"""
from alembic import op
import sqlalchemy as sa


revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


# Columns the retired migrate_v2/migrate_v3 scripts added to ``obligations`` on old databases.
_LEGACY_OBLIGATION_COLUMNS = [
    "previous_obligation_id",
    "amended_obligation_id",
    "superseded_obligation_id",
    "origin_circular_id",
    "clause_uuid",
    "source_type",
]


def _create_table(name: str, *columns) -> None:
    if not sa.inspect(op.get_bind()).has_table(name):
        op.create_table(name, *columns)


def _add_legacy_obligation_columns() -> None:
    inspector = sa.inspect(op.get_bind())
    existing = {c["name"] for c in inspector.get_columns("obligations")}
    for column in _LEGACY_OBLIGATION_COLUMNS:
        if column not in existing:
            op.add_column("obligations", sa.Column(column, sa.String(), nullable=True))


def upgrade() -> None:
    _create_table('audit_trail',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('thread_id', sa.String(), nullable=True),
    sa.Column('node_name', sa.String(), nullable=True),
    sa.Column('action', sa.JSON(), nullable=True),
    sa.Column('actor', sa.String(), nullable=True),
    sa.Column('timestamp', sa.DateTime(), nullable=True),
    sa.Column('prev_hash', sa.String(), nullable=True),
    sa.Column('hash', sa.String(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    _create_table('circulars',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('title', sa.String(), nullable=True),
    sa.Column('issue_date', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    _create_table('company_obligations',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('requirement', sa.Text(), nullable=True),
    sa.Column('frequency', sa.String(), nullable=True),
    sa.Column('evidence_type', sa.String(), nullable=True),
    sa.Column('deadline_rule', sa.String(), nullable=True),
    sa.Column('intermediary', sa.String(), nullable=True),
    sa.Column('owner', sa.String(), nullable=True),
    sa.Column('due_date', sa.DateTime(), nullable=True),
    sa.Column('status', sa.String(), nullable=True),
    sa.Column('imported_at', sa.DateTime(), nullable=True),
    sa.Column('source_file', sa.String(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    _create_table('gap_results',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('regulatory_obligation_id', sa.String(), nullable=True),
    sa.Column('company_obligation_id', sa.String(), nullable=True),
    sa.Column('gap_type', sa.String(), nullable=True),
    sa.Column('detail', sa.Text(), nullable=True),
    sa.Column('computed_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    _create_table('review_queue',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('circular_id', sa.String(), nullable=True),
    sa.Column('clause_id', sa.String(), nullable=True),
    sa.Column('previous_clause', sa.Text(), nullable=True),
    sa.Column('new_clause', sa.Text(), nullable=True),
    sa.Column('highlighted_diff', sa.Text(), nullable=True),
    sa.Column('llm_explanation', sa.Text(), nullable=True),
    sa.Column('confidence', sa.Float(), nullable=True),
    sa.Column('extracted_obligation', sa.JSON(), nullable=True),
    sa.Column('status', sa.String(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    _create_table('upload_jobs',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('filename', sa.String(), nullable=True),
    sa.Column('circular_id', sa.String(), nullable=True),
    sa.Column('status', sa.String(), nullable=True),
    sa.Column('total_clauses', sa.Integer(), nullable=True),
    sa.Column('processed_clauses', sa.Integer(), nullable=True),
    sa.Column('result', sa.JSON(), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    _create_table('workflow_state',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('state', sa.String(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    _create_table('sections',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('title', sa.String(), nullable=True),
    sa.Column('circular_id', sa.String(), nullable=True),
    sa.ForeignKeyConstraint(['circular_id'], ['circulars.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    _create_table('clauses',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('clause_number', sa.String(), nullable=True),
    sa.Column('text', sa.Text(), nullable=True),
    sa.Column('section_id', sa.String(), nullable=True),
    sa.ForeignKeyConstraint(['section_id'], ['sections.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    _create_table('obligations',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('clause_id', sa.String(), nullable=True),
    sa.Column('requirement', sa.Text(), nullable=True),
    sa.Column('frequency', sa.String(), nullable=True),
    sa.Column('evidence_type', sa.String(), nullable=True),
    sa.Column('deadline_rule', sa.String(), nullable=True),
    sa.Column('intermediary', sa.String(), nullable=True),
    sa.Column('status', sa.String(), nullable=True),
    sa.Column('source_type', sa.String(), nullable=True),
    sa.Column('previous_obligation_id', sa.String(), nullable=True),
    sa.Column('amended_obligation_id', sa.String(), nullable=True),
    sa.Column('superseded_obligation_id', sa.String(), nullable=True),
    sa.Column('origin_circular_id', sa.String(), nullable=True),
    sa.Column('clause_uuid', sa.String(), nullable=True),
    sa.ForeignKeyConstraint(['amended_obligation_id'], ['obligations.id'], ),
    sa.ForeignKeyConstraint(['clause_uuid'], ['clauses.id'], ),
    sa.ForeignKeyConstraint(['origin_circular_id'], ['circulars.id'], ),
    sa.ForeignKeyConstraint(['previous_obligation_id'], ['obligations.id'], ),
    sa.ForeignKeyConstraint(['superseded_obligation_id'], ['obligations.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    _create_table('applicable_entities',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('entity_name', sa.String(), nullable=True),
    sa.Column('obligation_id', sa.String(), nullable=True),
    sa.ForeignKeyConstraint(['obligation_id'], ['obligations.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    _create_table('deadlines',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('due_date', sa.DateTime(), nullable=True),
    sa.Column('status', sa.String(), nullable=True),
    sa.Column('obligation_id', sa.String(), nullable=True),
    sa.ForeignKeyConstraint(['obligation_id'], ['obligations.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    _create_table('evidence',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('file_ref', sa.String(), nullable=True),
    sa.Column('submitted_at', sa.DateTime(), nullable=True),
    sa.Column('obligation_id', sa.String(), nullable=True),
    sa.ForeignKeyConstraint(['obligation_id'], ['obligations.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    _create_table('tasks',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('obligation_id', sa.String(), nullable=True),
    sa.Column('owner', sa.String(), nullable=True),
    sa.Column('due_date', sa.DateTime(), nullable=True),
    sa.Column('status', sa.String(), nullable=True),
    sa.ForeignKeyConstraint(['obligation_id'], ['obligations.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    _create_table('evidence_log',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('task_id', sa.String(), nullable=True),
    sa.Column('file_ref', sa.String(), nullable=True),
    sa.Column('submitted_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    _add_legacy_obligation_columns()


def downgrade() -> None:
    op.drop_table('evidence_log')
    op.drop_table('tasks')
    op.drop_table('evidence')
    op.drop_table('deadlines')
    op.drop_table('applicable_entities')
    op.drop_table('obligations')
    op.drop_table('clauses')
    op.drop_table('sections')
    op.drop_table('workflow_state')
    op.drop_table('upload_jobs')
    op.drop_table('review_queue')
    op.drop_table('gap_results')
    op.drop_table('company_obligations')
    op.drop_table('circulars')
    op.drop_table('audit_trail')
