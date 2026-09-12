"""desktop.ai_call: what left this machine, and what it cost (PRD AI-2/3/5).

AI-5 asks that every call record its provider, model, purpose, token count and
a hash of the payload — "because we cannot audit what a provider does with a
prompt, so we audit what left". Upstream's `audit_event` has no payload column
and cannot carry that, so this table does, and an `audit_event` row is written
alongside it for the org trail.

It is also the spend cap (AI-2): the month's sum is read from here before each
call. Insert and select only — never update, never delete. An audit trail that
can be edited is not one, and a spend cap that can be zeroed is not one either.
"""

import sqlalchemy as sa
from alembic import op

from usali.tenancy import APP_DB_ROLE

revision = "d0004aicalls"
down_revision = "d0003mappingdecisions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_call",
        # Identity rather than serial: the sequence belongs to the column, so
        # the serving role needs no separate grant on it.
        sa.Column("call_id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column(
            "called_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(), index=True,
        ),
        sa.Column("actor_subject", sa.String(64), nullable=False),
        sa.Column("provider", sa.String(30), nullable=False),
        sa.Column("model", sa.String(120), nullable=False),
        sa.Column("purpose", sa.String(40), nullable=False),
        sa.Column("property_id", sa.String(50), nullable=True),
        sa.Column("prompt_tokens", sa.Integer, nullable=True),
        sa.Column("completion_tokens", sa.Integer, nullable=True),
        # NULL means "we could not price this", which is a real answer and is
        # why the cap also counts calls. It is never silently treated as zero.
        sa.Column("estimated_cost", sa.Numeric(12, 6), nullable=True),
        # What left, as a hash. Never the payload itself: keeping the prompt
        # would put transaction data in a second place for no added assurance.
        sa.Column("payload_sha256", sa.String(64), nullable=False),
        sa.Column("outcome", sa.String(20), nullable=False),
        sa.Column("message", sa.String(300), nullable=True),
        sa.CheckConstraint(
            "outcome IN ('answered', 'declined', 'refused', 'blocked', 'failed')",
            name="ck_ai_call_outcome",
        ),
        schema="desktop",
    )
    op.execute(f'GRANT SELECT, INSERT ON desktop.ai_call TO "{APP_DB_ROLE}"')


def downgrade() -> None:
    op.drop_table("ai_call", schema="desktop")
