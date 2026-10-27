"""Withheld-content filter: hard fallback patterns plus optional file patterns (stdlib only)."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional, Tuple

FALLBACK_PATTERNS = [
    r"EXP-013.*seed[_-]?([2-9]|\d{2,})",
    r"H108N",
    r"pp_seedext",
    r"cleanr1_",
    r"pp_ltf_",
]

_TEXT_EXT = {".tex", ".md", ".txt", ".csv", ".json"}
_NAME_ONLY_EXT = {".png", ".jpg", ".jpeg", ".svg"}


def _compile(patterns: List[str]) -> list:
    out = []
    for p in patterns:
        try:
            out.append(re.compile(p))
        except re.error:
            continue
    return out


class Withheld:
    def __init__(self, patterns: List[str]) -> None:
        # The fallback is always included, so an empty or broken source cannot disable it.
        self.patterns = list(FALLBACK_PATTERNS) + [p for p in patterns if p not in FALLBACK_PATTERNS]
        self._re = _compile(self.patterns)

    @classmethod
    def load(cls, source: Optional[Path]) -> "Withheld":
        extra: List[str] = []
        if source is not None:
            try:
                data = json.loads(Path(source).read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    data = data.get("patterns")
                if isinstance(data, list):
                    extra = [p for p in data if isinstance(p, str) and p]
            except (OSError, ValueError):
                extra = []
        return cls(extra)

    def _hit(self, text: str) -> bool:
        return any(r.search(text) for r in self._re)

    def name_hit(self, path: str) -> bool:
        return self._hit(str(path).replace("\\", "/"))

    def mask_text(self, text: str) -> Tuple[str, int]:
        lines = text.split("\n")
        count = 0
        for i, line in enumerate(lines):
            if self._hit(line):
                lines[i] = ""
                count += 1
        return "\n".join(lines), count

    def _pdf_text(self, path: Path) -> Optional[str]:
        exe = shutil.which("pdftotext")
        if not exe:
            return None
        try:
            r = subprocess.run([exe, "-q", str(path), "-"], timeout=30,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except (OSError, subprocess.SubprocessError):
            return None
        if r.returncode != 0:
            return None
        return r.stdout.decode("utf-8", "replace")

    def check_file(self, path: Path) -> str:
        path = Path(path)
        if self.name_hit(str(path)):
            return "deny_name"
        ext = path.suffix.lower()
        if ext in _NAME_ONLY_EXT:
            return "ok"
        if ext == ".pdf":
            text = self._pdf_text(path)
        elif ext in _TEXT_EXT:
            try:
                text = path.read_bytes().decode("utf-8", "replace")
            except OSError:
                return "deny_unscannable"
        else:
            return "deny_unscannable"
        if text is None:
            return "deny_unscannable"
        return "deny_content" if self._hit(text) else "ok"
