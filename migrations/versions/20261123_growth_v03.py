"""Baseline / safe upgrade from original Research Writer schema to Growth v0.3.

Revision ID: growth_v03
Revises:
Create Date: 2026-11-23
"""
from alembic import op
from sqlalchemy import inspect, text

revision = 'growth_v03'
down_revision = None
branch_labels = None
depends_on = None


# Only additive modifications. Existing rows are never changed or deleted.
COLUMNS = {
    'posts': {
        'language': "VARCHAR(20) DEFAULT 'ru'",
        'campaign_id': 'INTEGER',
        'offer_id': 'INTEGER',
        'goal': "VARCHAR(30) DEFAULT 'discussion'",
        'hook_type': 'VARCHAR(40)',
        'variant_index': 'INTEGER',
        'editorial_score': 'FLOAT',
        'prompt_version': 'VARCHAR(40)',
        'ai_model': 'VARCHAR(120)',
        'tracking_url': 'VARCHAR(1000)',
    },
    'writer_briefs': {'language': "VARCHAR(20) DEFAULT 'ru'"},
}


def upgrade():
    from app.database.session import Base
    from app.database import models  # noqa F401
    from app.config import settings

    connection = op.get_bind()
    # Fresh installs: create the complete v0.3 schema (also research tables).
    # Existing installations: create only missing tables; preserve every row.
    Base.metadata.create_all(bind=connection, checkfirst=True)
    for table, columns in COLUMNS.items():
        if table not in inspect(connection).get_table_names():
            continue
        current = {c['name'] for c in inspect(connection).get_columns(table)}
        for name, ddl in columns.items():
            if name not in current:
                op.execute(text(f'ALTER TABLE {table} ADD COLUMN {name} {ddl}'))

    from app.database.models import AffiliateOffer
    from sqlalchemy import select
    if connection.execute(select(AffiliateOffer.id).where(AffiliateOffer.slug == 'fomo')).first() is None:
        connection.execute(AffiliateOffer.__table__.insert().values(
            slug='fomo', name='FOMO', referral_url=settings.base_referral_url,
            description='Поиск криптоактивов и активность трейдеров. Не обещать доходность.',
            target_audience='Криптоэнтузиасты, мемкоины, исследование рынка',
            benefits_json=[], active=True))


def downgrade():
    raise RuntimeError('Data-preserving downgrade is not supported. Restore a DB backup.')
