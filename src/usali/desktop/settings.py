"""Read and write `desktop.setting` (see migrations/versions/d0001_settings.py).

Plain SQL on purpose: the table is not org-scoped, so it sits outside the
ORM's tenancy hook, and a JSON value per key is all it needs to be.
"""

import json

from sqlalchemy import text
from sqlalchemy.orm import Session

MODULES_KEY = "modules"


def read_setting(session: Session, key: str) -> object | None:
    return session.execute(
        text("SELECT value FROM desktop.setting WHERE key = :k"), {"k": key}
    ).scalar()


def write_setting(session: Session, key: str, value: object) -> None:
    session.execute(
        text(
            "INSERT INTO desktop.setting (key, value) VALUES (:k, CAST(:v AS jsonb)) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()"
        ),
        {"k": key, "v": json.dumps(value)},
    )


def read_modules(session: Session) -> list[str] | None:
    """The owner's stored module choice, or None if they never made one."""
    value = read_setting(session, MODULES_KEY)
    if isinstance(value, list) and all(isinstance(v, str) for v in value):
        return list(value)
    return None
