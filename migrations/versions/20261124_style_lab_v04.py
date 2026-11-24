"""Style Lab pattern library, additive migration.

Revision ID: style_lab_v04
Revises: growth_v03
"""
from alembic import op

revision = "style_lab_v04"
down_revision = "growth_v03"
branch_labels = None
depends_on = None


def upgrade():
    from app.database.models import StylePattern
    StylePattern.__table__.create(bind=op.get_bind(), checkfirst=True)


def downgrade():
    raise RuntimeError("No destructive downgrade; restore a backup instead.")
