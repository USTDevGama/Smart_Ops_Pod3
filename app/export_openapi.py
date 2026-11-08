"""Regenerate the generated docs: `python -m app.export_openapi`.

Writes docs/openapi.yaml (the API), docs/roleplay_result.schema.json (the outgoing Pod D
contract), and docs/scoring_output.schema.json (the expected final criterion-level output from
the conversation-agent component).
"""

import json
from pathlib import Path

import yaml

from app.main import app
from app.schemas import RoleplayResult, ScoringOutput

DOCS = Path(__file__).resolve().parent.parent / "docs"


def main() -> None:
    DOCS.mkdir(parents=True, exist_ok=True)
    (DOCS / "openapi.yaml").write_text(yaml.safe_dump(app.openapi(), sort_keys=False), "utf-8")
    schema = RoleplayResult.model_json_schema()
    (DOCS / "roleplay_result.schema.json").write_text(json.dumps(schema, indent=2) + "\n", "utf-8")
    scoring_schema = ScoringOutput.model_json_schema()
    (DOCS / "scoring_output.schema.json").write_text(
        json.dumps(scoring_schema, indent=2) + "\n", "utf-8"
    )
    print(
        f"wrote {DOCS / 'openapi.yaml'}, {DOCS / 'roleplay_result.schema.json'} "
        f"and {DOCS / 'scoring_output.schema.json'}"
    )


if __name__ == "__main__":
    main()
