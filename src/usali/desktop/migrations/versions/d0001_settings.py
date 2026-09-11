"""desktop.setting: the local settings table (PRD 5.4) — module choice first.

Not org-scoped: one install is one owner's machine, and these settings
describe the install, not a tenant. The serving role reads and writes it;
it never deletes, and holds nothing else in this schema.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

from usali.tenancy import APP_DB_ROLE

revision = "d0001settings"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "setting",
        sa.Column("key", sa.String(100), primary_key=True),
        sa.Column("value", JSONB, nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        schema="desktop",
    )
    op.execute(f'GRANT USAGE ON SCHEMA desktop TO "{APP_DB_ROLE}"')
    op.execute(f'GRANT SELECT, INSERT, UPDATE ON desktop.setting TO "{APP_DB_ROLE}"')


def downgrade() -> None:
    op.drop_table("setting", schema="desktop")
