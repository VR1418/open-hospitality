"""desktop.statement and desktop.statement_line: bank and card statements the
owner uploaded, with each line's match (bank) or category (card).

See usali.desktop.statements. The file itself is not kept; its lines are.
Nothing here posts to the books — it is a check against them.
"""

import sqlalchemy as sa
from alembic import op

from usali.tenancy import APP_DB_ROLE

revision = "d0006statements"
down_revision = "d0005reportrecipes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "statement",
        sa.Column("statement_id", sa.Integer, sa.Identity(), primary_key=True),
        sa.Column("property_id", sa.String(50), nullable=False),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("account_label", sa.String(100), nullable=False),
        sa.Column("file_name", sa.String(255), nullable=False),
        sa.Column("uploaded_by", sa.String(64), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("first_date", sa.Date, nullable=False),
        sa.Column("last_date", sa.Date, nullable=False),
        sa.CheckConstraint("kind IN ('bank', 'card')", name="ck_statement_kind"),
        schema="desktop",
    )
    op.create_table(
        "statement_line",
        sa.Column("line_id", sa.Integer, sa.Identity(), primary_key=True),
        sa.Column("statement_id", sa.Integer,
                  sa.ForeignKey("desktop.statement.statement_id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("posted_on", sa.Date, nullable=False),
        sa.Column("description", sa.String(300), nullable=False),
        sa.Column("amount", sa.Numeric(15, 2), nullable=False),
        sa.Column("balance", sa.Numeric(15, 2), nullable=True),
        # bank: settlement | cash | payroll | unmatched | ignored
        sa.Column("match_kind", sa.String(20), nullable=False, server_default="unmatched"),
        sa.Column("match_note", sa.String(300), nullable=True),
        sa.Column("matched_amount", sa.Numeric(15, 2), nullable=True),
        # card: one of statements.CARD_CATEGORIES, or NULL until sorted
        sa.Column("category", sa.String(100), nullable=True),
        schema="desktop",
    )
    op.create_index("ix_statement_line_statement", "statement_line", ["statement_id"],
                    schema="desktop")
    for table in ("statement", "statement_line"):
        op.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON desktop.{table} TO "{APP_DB_ROLE}"')


def downgrade() -> None:
    op.drop_table("statement_line", schema="desktop")
    op.drop_table("statement", schema="desktop")
