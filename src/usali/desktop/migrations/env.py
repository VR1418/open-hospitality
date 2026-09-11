"""The desktop edition's OWN migration chain (schema `desktop`).

Kept apart from upstream's chain on purpose: a fork that adds revisions to
upstream's history grows a second head at every rebase. This chain has its
own version table inside its own schema, and touches nothing of upstream's.
"""

from alembic import context
from sqlalchemy import create_engine, pool, text

from usali.desktop.migrations.env_names import SCHEMA, VERSION_TABLE

url = context.config.get_main_option("sqlalchemy.url")
if url is None:
    raise RuntimeError("the desktop migration chain needs sqlalchemy.url")

engine = create_engine(url, poolclass=pool.NullPool)
with engine.connect() as connection:
    # The version table lives in the schema, so the schema must exist first.
    connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}"))
    connection.commit()
    context.configure(
        connection=connection,
        target_metadata=None,
        version_table=VERSION_TABLE,
        version_table_schema=SCHEMA,
    )
    with context.begin_transaction():
        context.run_migrations()
