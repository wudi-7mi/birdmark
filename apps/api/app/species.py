from __future__ import annotations

import sqlite3
from typing import Any


def ensure_species_for_prediction(
    db: sqlite3.Connection,
    prediction: dict[str, Any],
) -> int | None:
    scientific_name = prediction.get("species")
    if not scientific_name:
        return None

    return ensure_species(
        db,
        scientific_name=scientific_name,
        common_name=prediction.get("common_name"),
        genus=prediction.get("genus"),
        family=prediction.get("family"),
        source="bioclip",
    )


def ensure_species(
    db: sqlite3.Connection,
    *,
    scientific_name: str,
    common_name: str | None = None,
    chinese_name: str | None = None,
    genus: str | None = None,
    family: str | None = None,
    source: str | None = None,
) -> int:
    normalized_name = scientific_name.strip()
    if not normalized_name:
        raise ValueError("scientific_name is required")

    existing = db.execute(
        "SELECT id FROM species WHERE scientific_name = ?",
        (normalized_name,),
    ).fetchone()
    if existing is not None:
        return int(existing["id"])

    cursor = db.execute(
        """
        INSERT INTO species (
            scientific_name, common_name, chinese_name, genus, family, source
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            normalized_name,
            common_name,
            chinese_name,
            genus,
            family,
            source,
        ),
    )
    return int(cursor.lastrowid)
