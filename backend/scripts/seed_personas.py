"""Seed personas from JSON fixture files into the database.

Reads all JSON files from ``backend/fixtures/personas/``, creates system
personas (``user_id=None``) via :class:`PersonaService`, and syncs
``is_default`` plus prompt fields on personas that already exist so fixture
changes stay repeatable.  Can be run standalone::

    python -m backend.scripts.seed_personas

Or imported and called programmatically::

    from backend.scripts.seed_personas import seed_personas
    seed_personas()
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

from sqlalchemy.orm import Session as DBSession

from backend.config import settings
from backend.database import Base, get_engine, get_session_maker
from backend.models.persona import Persona
from backend.services.persona_service import PersonaService

logger = logging.getLogger(__name__)

# Resolved at import time so the module works regardless of cwd.
_DEFAULT_FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "personas"


def _persona_fields(data: dict) -> dict:
    """Normalize fixture fields used for create/update."""
    return {
        "system_prompt": data.get("system_prompt", ""),
        "description": data.get("description"),
        "temperature": float(data.get("temperature", 0.7)),
        "model_id": data.get("model_id"),
        "is_default": bool(data.get("is_default", False)),
    }


def _fields_changed(persona: Persona, fields: dict) -> bool:
    return (
        persona.system_prompt != fields["system_prompt"]
        or persona.description != fields["description"]
        or persona.temperature != fields["temperature"]
        or persona.model_id != fields["model_id"]
        or bool(persona.is_default) != fields["is_default"]
    )


def _apply_fixture(
    svc: PersonaService,
    db: DBSession,
    data: dict,
    result: dict[str, list[str]],
) -> str | None:
    """Create or sync one system persona from a fixture. Returns the name."""
    name = data.get("name")
    if not name:
        return None
    fields = _persona_fields(data)
    existing = (
        db.query(Persona)
        .filter(Persona.name == name, Persona.user_id.is_(None))
        .first()
    )
    if existing is None:
        svc.create_persona(user_id=None, name=name, **fields)
        logger.info("Seeded persona: %s", name)
        result["seeded"].append(name)
        return name
    if not _fields_changed(existing, fields):
        logger.info("Skipped (already exists): %s", name)
        result["skipped"].append(name)
        return name
    svc.update_system_persona(existing.id, **fields)
    logger.info("Updated persona from fixture: %s", name)
    result["updated"].append(name)
    return name


def _clear_stale_defaults(
    svc: PersonaService,
    db: DBSession,
    default_names: set[str],
    result: dict[str, list[str]],
) -> None:
    """Unset is_default on system personas not declared default in fixtures."""
    extras = (
        db.query(Persona)
        .filter(Persona.user_id.is_(None), Persona.is_default.is_(True))
        .all()
    )
    for persona in extras:
        if persona.name in default_names:
            continue
        svc.update_system_persona(persona.id, is_default=False)
        if persona.name not in result["updated"] and persona.name not in result["seeded"]:
            result["updated"].append(persona.name)
        if persona.name in result["skipped"]:
            result["skipped"].remove(persona.name)
        logger.info("Cleared leftover default flag: %s", persona.name)


def seed_personas(
    db: DBSession | None = None,
    fixtures_dir: Path | None = None,
) -> dict[str, list[str]]:
    """Load persona fixtures and insert missing ones into the database.

    Args:
        db: An existing SQLAlchemy session.  When ``None`` a new session is
            created from :data:`backend.config.settings`.
        fixtures_dir: Directory containing ``*.json`` fixture files.  Defaults
            to ``backend/fixtures/personas/``.

    Returns:
        A dict with ``"seeded"``, ``"skipped"``, and ``"updated"`` lists of
        persona names.
    """
    own_session = False
    if db is None:
        engine = get_engine(settings.database_url)
        Base.metadata.create_all(bind=engine)
        session_maker = get_session_maker(engine)
        db = session_maker()
        own_session = True

    fixtures_dir = fixtures_dir or _DEFAULT_FIXTURES_DIR
    result: dict[str, list[str]] = {"seeded": [], "skipped": [], "updated": []}

    try:
        json_files = sorted(fixtures_dir.glob("*.json")) if fixtures_dir.is_dir() else []
        if not json_files:
            logger.info("No persona fixture files found in %s", fixtures_dir)
            return result

        svc = PersonaService(db)
        default_names: set[str] = set()

        for filepath in json_files:
            try:
                data = json.loads(filepath.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Skipping malformed fixture %s: %s", filepath.name, exc)
                continue

            name = data.get("name")
            if not name:
                logger.warning("Skipping fixture %s: missing 'name' field", filepath.name)
                continue

            if bool(data.get("is_default", False)):
                default_names.add(name)
            _apply_fixture(svc, db, data, result)

        _clear_stale_defaults(svc, db, default_names, result)

    finally:
        if own_session:
            db.close()

    return result


def main() -> None:
    """CLI entry point."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    result = seed_personas()
    seeded, skipped, updated = (
        result["seeded"],
        result["skipped"],
        result.get("updated", []),
    )
    logger.info(
        "Done — %d seeded, %d skipped, %d updated.",
        len(seeded),
        len(skipped),
        len(updated),
    )
    if not seeded and not skipped:
        sys.exit(0)


if __name__ == "__main__":
    main()
