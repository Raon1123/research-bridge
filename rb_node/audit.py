"""Append-only JSONL audit log. Never records message bodies or file contents."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

_DROP = ("body", "content", "data")


class Audit:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def record(self, **fields: object) -> None:
        rec = {k: v for k, v in fields.items() if k not in _DROP}
        rec.setdefault("ts", time.strftime("%Y-%m-%dT%H:%M:%S%z"))
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            new = not self.path.exists()
            with open(str(self.path), "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            if new:
                try:
                    os.chmod(str(self.path), 0o600)
                except OSError:
                    pass
        except OSError:
            pass  # auditing must not break serving
