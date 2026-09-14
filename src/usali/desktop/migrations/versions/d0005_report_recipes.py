"""desktop.report_recipe: how THIS hotel's reports of one shape are read.

Learned from rows the owner confirmed (usali.desktop.ai.recipes): the app
infers a recipe that reproduces them exactly, and later reports of that shape
are read by replaying it with no model call. Keyed by hotel and the shape's
fingerprint, so a changed layout is a new shape, not an overwrite.

The recipe column holds data naming one of the app's own layouts, never a
pattern (`Recipe.from_json` refuses anything else). The serving role may read,
insert and update; forgetting a recipe is not a DELETE from here, the
`mapping_decision` rule.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

from usali.tenancy import APP_DB_ROLE

revision = "d0005reportrecipes"
down_revision = "d0004aicalls"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "report_recipe",
        sa.Column("property_id", sa.String(50), primary_key=True),
        sa.Column("fingerprint", sa.String(64), primary_key=True),
        sa.Column("recipe", JSONB, nullable=False),
        sa.Column("confirmed_by", sa.String(64), nullable=False),
        sa.Column(
            "confirmed_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("reads", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_read_at", sa.DateTime(timezone=True), nullable=True),
        schema="desktop",
    )
    op.execute(f'GRANT SELECT, INSERT, UPDATE ON desktop.report_recipe TO "{APP_DB_ROLE}"')


def downgrade() -> None:
    op.drop_table("report_recipe", schema="desktop")
