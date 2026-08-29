"""Load and validate the dashboard's language-neutral JSON contracts."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from .config import CONTRACTS_ROOT


SCHEMAS = {
    "market-dataset-v1": "market-dataset-v1.schema.json",
    "chart-study-v2": "chart-study-v2.schema.json",
    "study-run-v1": "study-run-v1.schema.json",
}


@lru_cache(maxsize=None)
def load_schema(name: str) -> dict[str, Any]:
    try:
        filename = SCHEMAS[name]
    except KeyError as exc:
        raise KeyError(f"Unknown dashboard schema: {name}") from exc
    return json.loads((CONTRACTS_ROOT / filename).read_text(encoding="utf-8"))


def validate_document(document: dict[str, Any], schema_name: str) -> None:
    registry = Registry()
    for name in SCHEMAS:
        schema = load_schema(name)
        registry = registry.with_resource(schema["$id"], Resource.from_contents(schema))
    validator = Draft202012Validator(load_schema(schema_name), registry=registry)
    errors = sorted(validator.iter_errors(document), key=lambda item: list(item.absolute_path))
    if not errors:
        return
    details = []
    for error in errors[:8]:
        location = ".".join(str(part) for part in error.absolute_path) or "<root>"
        details.append(f"{location}: {error.message}")
    raise ValueError(f"Invalid {schema_name} document: {'; '.join(details)}")


def contract_files() -> list[Path]:
    return [CONTRACTS_ROOT / filename for filename in SCHEMAS.values()]
