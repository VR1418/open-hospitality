"""Keeping learned recipes (desktop.report_recipe) — see usali.desktop.ai.recipes."""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from usali.desktop.ai.pages import Page
from usali.desktop.ai.recipes import Recipe, Row, replay


@dataclass(frozen=True)
class Stored:
    recipe: Recipe
    confirmed_at: datetime
    reads: int
    last_read_at: datetime | None


def for_property(session: Session, property_id: str) -> list[Stored]:
    rows = session.execute(
        text(
            "SELECT recipe, confirmed_at, reads, last_read_at FROM desktop.report_recipe "
            "WHERE property_id = :p ORDER BY confirmed_at DESC"
        ),
        {"p": property_id},
    ).all()
    out: list[Stored] = []
    for raw, confirmed_at, reads, last_read_at in rows:
        recipe = Recipe.from_json(raw if isinstance(raw, dict) else json.loads(raw))
        if recipe is not None:  # a row that no longer names a known layout is ignored
            out.append(Stored(recipe, confirmed_at, int(reads), last_read_at))
    return out


def save(session: Session, property_id: str, recipe: Recipe, confirmed_by: str) -> None:
    """Keep a recipe, or replace the one for the same shape. Does not commit."""
    session.execute(
        text(
            "INSERT INTO desktop.report_recipe (property_id, fingerprint, recipe, confirmed_by) "
            "VALUES (:p, :f, CAST(:r AS jsonb), :by) "
            "ON CONFLICT (property_id, fingerprint) DO UPDATE SET recipe = EXCLUDED.recipe, "
            "confirmed_by = EXCLUDED.confirmed_by, confirmed_at = now()"
        ),
        {"p": property_id, "f": recipe.fingerprint, "r": json.dumps(recipe.to_json()),
         "by": confirmed_by},
    )


def read_with_memory(
    session: Session, property_id: str, pages: Sequence[Page]
) -> tuple[Stored, tuple[object, list[Row]]] | None:
    """The first stored recipe that reads these pages, counted as a read.
    Does not commit."""
    for stored in for_property(session, property_id):
        got = replay(stored.recipe, pages)
        if got is not None:
            session.execute(
                text(
                    "UPDATE desktop.report_recipe SET reads = reads + 1, last_read_at = now() "
                    "WHERE property_id = :p AND fingerprint = :f"
                ),
                {"p": property_id, "f": stored.recipe.fingerprint},
            )
            return stored, got
    return None
