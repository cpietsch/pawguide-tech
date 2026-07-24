#!/usr/bin/env python3
"""Export the gateway schema used for operator-client generation."""

from __future__ import annotations

import json
from pathlib import Path

from pawguide.app import create_app


def main() -> None:
    project_dir = Path(__file__).resolve().parent.parent
    output_path = project_dir / "contracts" / "pawguide-openapi.json"
    app = create_app(
        operator_token="schema-operator-token",
        dev_token="schema-developer-token",
    )
    output_path.write_text(
        json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(output_path)


if __name__ == "__main__":
    main()
