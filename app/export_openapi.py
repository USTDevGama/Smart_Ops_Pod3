"""Regenerate the generated docs: `python -m app.export_openapi`.

Writes docs/openapi.yaml (the API) and docs/roleplay_result.schema.json (the program's
result format, generated from our model so the two can never drift).
"""

import json
from pathlib import Path

import yaml

from app.main import app
from app.schemas import RoleplayResult

DOCS = Path(__file__).resolve().parent.parent / "docs"


def main() -> None:
    DOCS.mkdir(parents=True, exist_ok=True)
    (DOCS / "openapi.yaml").write_text(yaml.safe_dump(app.openapi(), sort_keys=False), "utf-8")
    schema = RoleplayResult.model_json_schema()
    (DOCS / "roleplay_result.schema.json").write_text(json.dumps(schema, indent=2) + "\n", "utf-8")
    print(f"wrote {DOCS / 'openapi.yaml'} and {DOCS / 'roleplay_result.schema.json'}")


if __name__ == "__main__":
    main()
