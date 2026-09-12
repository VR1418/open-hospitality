"""desktop.mapping_decision: what THIS hotel's transaction codes mean.

Upstream's `usali_mapping_dictionary` is keyed (pms_source, pms_trx_code,
usali_edition) with no property and no org, so a group's two hotels cannot
both be right about a code — and choiceADVANTAGE codes are franchise-
configurable, which is why `mapping/skytouch.yaml` ships every row as
confidence LOW / review_status needs-review. This table holds the answer a
person actually confirmed, per hotel, with their name on it.

The natural key IS the identity, so it is the primary key: one decision per
(hotel, source, code, edition). The serving role may read, insert and update
— never delete: correcting a decision replaces its fields and re-stamps
`decided_by`, while the audit trail keeps every change on record. Reverting
to the shipped dictionary is deliberately not a DELETE from here.
"""

import sqlalchemy as sa
from alembic import op

from usali.tenancy import APP_DB_ROLE

revision = "d0003mappingdecisions"
down_revision = "d0002accounts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mapping_decision",
        sa.Column("property_id", sa.String(50), primary_key=True),
        sa.Column("pms_source", sa.String(20), primary_key=True),
        sa.Column("pms_trx_code", sa.String(50), primary_key=True),
        sa.Column("usali_edition", sa.Integer, primary_key=True),
        # The five fields a fact copies — `transform.Classification`.
        # A NULL schedule id is meaningful, not missing: it is what puts a
        # code in taxes/settlements/non-operating rather than revenue.
        sa.Column("usali_schedule_id", sa.Integer, nullable=True),
        sa.Column("usali_major_category", sa.String(100), nullable=False),
        sa.Column("usali_sub_category", sa.String(100), nullable=False),
        sa.Column("usali_line_item", sa.String(100), nullable=False),
        sa.Column("gl_account_code", sa.String(50), nullable=True),
        # 'owner' is a person who chose it; 'ai-accepted' is a person who
        # accepted a suggestion (PRD AI-6 — a suggestion is never applied
        # without a click, and the click is recorded).
        sa.Column("origin", sa.String(20), nullable=False),
        sa.Column("note", sa.String(500), nullable=True),
        sa.Column("decided_by", sa.String(64), nullable=False),
        sa.Column(
            "decided_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "origin IN ('owner', 'ai-accepted')", name="ck_mapping_decision_origin"
        ),
        schema="desktop",
    )
    op.execute(f'GRANT SELECT, INSERT, UPDATE ON desktop.mapping_decision TO "{APP_DB_ROLE}"')


def downgrade() -> None:
    op.drop_table("mapping_decision", schema="desktop")
