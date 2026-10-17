"""source location on clauses and review queue

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-17 17:59:34.202990
"""
from alembic import op
import sqlalchemy as sa


revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('clauses', schema=None) as batch_op:
        batch_op.add_column(sa.Column('page', sa.Integer(), nullable=True))

    with op.batch_alter_table('review_queue', schema=None) as batch_op:
        batch_op.add_column(sa.Column('clause_uuid', sa.String(), nullable=True))
        batch_op.add_column(sa.Column('clause_number', sa.String(), nullable=True))
        batch_op.add_column(sa.Column('section', sa.String(), nullable=True))
        batch_op.add_column(sa.Column('page', sa.Integer(), nullable=True))



def downgrade() -> None:
    with op.batch_alter_table('review_queue', schema=None) as batch_op:
        batch_op.drop_column('page')
        batch_op.drop_column('section')
        batch_op.drop_column('clause_number')
        batch_op.drop_column('clause_uuid')

    with op.batch_alter_table('clauses', schema=None) as batch_op:
        batch_op.drop_column('page')

