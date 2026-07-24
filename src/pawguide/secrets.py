"""Secret loading helpers shared by the gateway and command-line client."""

from __future__ import annotations

import os
from pathlib import Path


def read_secret(name: str) -> str:
    """Read a non-empty secret from ``name`` or ``name_FILE``.

    The file form keeps credentials out of systemd environment files and
    process listings. Defining both forms is rejected to avoid ambiguity.
    """

    direct = os.getenv(name)
    file_name = os.getenv(f"{name}_FILE")
    if direct is not None and file_name is not None:
        raise RuntimeError(f"set only one of {name} and {name}_FILE")

    if direct is not None:
        value = direct.strip()
    elif file_name is not None:
        try:
            value = Path(file_name).read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise RuntimeError(f"could not read {name}_FILE") from exc
    else:
        raise RuntimeError(f"{name} or {name}_FILE must be set")

    if not value:
        raise RuntimeError(f"{name} must not be empty")
    return value
