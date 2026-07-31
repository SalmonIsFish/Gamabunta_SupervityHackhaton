"""extend policy model for multi-action and tags

Revision ID: c4d774662adb
Revises: 45f28389e7cd
Create Date: 2026-07-31 14:45:47.738835

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c4d774662adb'
down_revision: Union[str, None] = '45f28389e7cd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # NOTE: autogenerate also detected pre-existing drift unrelated to this
    # change (orphaned items.status/items.priority columns, two missing
    # audit_logs indexes) — trimmed per CLAUDE.md's standing note not to let
    # that drift ride along with an unrelated migration.
    #
    # `tags`/`policy_scope` are NOT NULL — server_default backfills existing
    # rows (the 4 seeded procurement policies) so this doesn't fail on an
    # already-populated table.
    op.add_column('policies', sa.Column('actions', sa.JSON(), nullable=True))
    op.add_column('policies', sa.Column('tags', sa.JSON(), nullable=False, server_default='[]'))
    op.add_column('policies', sa.Column('entity_name', sa.String(length=255), nullable=True))
    op.add_column('policies', sa.Column('policy_scope', sa.String(length=20), nullable=False, server_default='custom'))
    op.add_column('policies', sa.Column('summary', sa.Text(), nullable=True))
    op.add_column('policies', sa.Column('refined_instruction', sa.Text(), nullable=True))
    op.add_column('policies', sa.Column('ai_instruction', sa.Text(), nullable=True))
    op.add_column('policies', sa.Column('source', sa.String(length=50), nullable=True))


def downgrade() -> None:
    op.drop_column('policies', 'source')
    op.drop_column('policies', 'ai_instruction')
    op.drop_column('policies', 'refined_instruction')
    op.drop_column('policies', 'summary')
    op.drop_column('policies', 'policy_scope')
    op.drop_column('policies', 'entity_name')
    op.drop_column('policies', 'tags')
    op.drop_column('policies', 'actions')
