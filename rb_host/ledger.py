"""Append-only JSONL ledger; readers take the last line per id."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional


class Ledger:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def _lines(self) -> List[dict]:
        if not self.path.is_file():
            return []
        out = []
        with open(str(self.path), "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue  # torn trailing line from a crash
                if isinstance(rec, dict):
                    out.append(rec)
        return out

    def _write(self, rec: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(str(self.path), "ab") as fh:
            fh.write((json.dumps(rec, ensure_ascii=False) + "\n").encode("utf-8"))

    def _latest(self) -> Dict[str, dict]:
        latest = {}  # type: Dict[str, dict]
        for r in self._lines():
            if "id" in r:
                latest[r["id"]] = r
        return latest

    def append(self, rec: dict) -> bool:
        key = (rec.get("kind"), rec.get("id"))
        for r in self._lines():
            if (r.get("kind"), r.get("id")) == key:
                return False
        self._write(rec)
        return True

    def get(self, id: str) -> Optional[dict]:
        return self._latest().get(id)

    def update(self, id: str, **fields: object) -> dict:
        cur = self.get(id)
        if cur is None:
            raise KeyError(id)
        new = dict(cur)
        new.update(fields)
        self._write(new)
        return new

    def thread(self, msg_id: str) -> List[dict]:
        return [r for r in self._latest().values()
                if r.get("id") == msg_id or r.get("reply_to") == msg_id
                or r.get("msg_id") == msg_id]

    def pending_jobs(self) -> List[dict]:
        return [r for r in self._latest().values()
                if r.get("kind") == "job" and r.get("status") == "pending_approval"]
