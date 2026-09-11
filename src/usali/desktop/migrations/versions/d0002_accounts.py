"""desktop.account + desktop.session: local sign-in (PRD A-1 to A-7, ADR-D1).

An account's `subject` is what upstream's `role_assignment.keycloak_subject`
and every audit row already key on, so authority stays in upstream's
tables, under upstream's row-level security; this schema only answers "who
is this, and is this sign-in still live?". The serving role may read,
insert and update — never delete: a disabled account and a revoked session
stay on record.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY

from usali.tenancy import APP_DB_ROLE

revision = "d0002accounts"
down_revision = "d0001settings"
branch_labels = None
depends_on = None

_TZ = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "account",
        sa.Column("subject", sa.String(64), primary_key=True),
        # Stored lower-cased; sign-in accepts the username or the email.
        sa.Column("username", sa.String(200), nullable=False, unique=True),
        sa.Column("email", sa.String(320), nullable=True),
        sa.Column("full_name", sa.String(200), nullable=False),
        # The COARSE token roles only (the operator door). Authority is
        # upstream's role_assignment grants, read under the org's RLS.
        sa.Column("realm_roles", ARRAY(sa.String(50)), nullable=False, server_default="{}"),
        sa.Column("password_hash", sa.Text, nullable=True),
        sa.Column("setup_code_hash", sa.Text, nullable=True),
        sa.Column("setup_code_expires_at", _TZ, nullable=True),
        sa.Column("recovery_code_hash", sa.Text, nullable=True),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("failed_attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("locked_until", _TZ, nullable=True),
        sa.Column("password_changed_at", _TZ, nullable=True),
        sa.Column("created_at", _TZ, nullable=False, server_default=sa.func.now()),
        schema="desktop",
    )
    op.create_index(
        "uq_account_email", "account", [sa.text("lower(email)")],
        unique=True, schema="desktop", postgresql_where=sa.text("email IS NOT NULL"),
    )
    op.create_table(
        "session",
        sa.Column("session_id", sa.String(64), primary_key=True),
        sa.Column(
            "subject", sa.String(64),
            sa.ForeignKey("desktop.account.subject"), nullable=False, index=True,
        ),
        sa.Column("device_label", sa.String(200), nullable=False),
        sa.Column("created_at", _TZ, nullable=False, server_default=sa.func.now()),
        sa.Column("last_seen_at", _TZ, nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", _TZ, nullable=False),
        sa.Column("revoked_at", _TZ, nullable=True),
        schema="desktop",
    )
    op.execute(
        f'GRANT SELECT, INSERT, UPDATE ON desktop.account, desktop.session TO "{APP_DB_ROLE}"'
    )


def downgrade() -> None:
    op.drop_table("session", schema="desktop")
    op.drop_index("uq_account_email", table_name="account", schema="desktop")
    op.drop_table("account", schema="desktop")
