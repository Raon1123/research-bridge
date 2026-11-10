"""Withheld-content filter: hard fallback patterns plus optional file patterns (stdlib only)."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import unicodedata
from pathlib import Path
from typing import List, Optional, Tuple

FALLBACK_PATTERNS = [
    r"EXP-013.*seed[_-]?([2-9]|\d{2,})",
    r"H108N",
    r"pp_seedext",
    r"cleanr1_",
    r"pp_ltf_",
]

# .svg is XML text (labels live in <text> elements), so it is scanned, not name-checked only.
_TEXT_EXT = {".tex", ".md", ".txt", ".csv", ".json", ".svg"}
_NAME_ONLY_EXT = {".png", ".jpg", ".jpeg"}


def _compile_report(patterns: List[str]) -> Tuple[list, List[int]]:
    """Compiled patterns and the indexes (into `patterns`) of those that failed to compile."""
    out = []
    failed = []  # type: List[int]
    for i, p in enumerate(patterns):
        try:
            out.append(re.compile(p))
        except re.error:
            failed.append(i)
    return out, failed


def _compile(patterns: List[str]) -> list:
    return _compile_report(patterns)[0]


def _as_list(v: object) -> list:
    return v if isinstance(v, list) else []


class Withheld:
    def __init__(self, patterns: List[str]) -> None:
        # The fallback is always included, so an empty or broken source cannot disable it.
        self.patterns = list(FALLBACK_PATTERNS) + [p for p in patterns if p not in FALLBACK_PATTERNS]
        self._re = _compile(self.patterns)
        # Indexes into `patterns` (the source list) that failed to compile; fallbacks never appear.
        self.rejected_indexes = [i for i, p in enumerate(patterns)
                                 if p not in FALLBACK_PATTERNS and not _compile([p])]  # type: List[int]
        self.rejected_count = len(self.rejected_indexes)
        self.source_set = False
        # Set by load(): None, "unreadable" or "unparseable" when a source was given but unusable.
        self.source_error = None  # type: Optional[str]
        # Compiled patterns from the source, without duplicates of the fallback patterns.
        self.extra_count = len(self.patterns) - len(FALLBACK_PATTERNS) - self.rejected_count

    @classmethod
    def load(cls, source: Optional[Path]) -> "Withheld":
        extra: List[str] = []
        error = None  # type: Optional[str]
        if source is not None:
            try:
                raw = Path(source).read_text(encoding="utf-8")
            except OSError:
                raw = None
                error = "unreadable"
            except ValueError:  # not UTF-8
                raw = None
                error = "unparseable"
            try:
                if raw is None:
                    raise ValueError
                data = json.loads(raw)
                found: list = []
                if isinstance(data, dict):
                    found.extend(_as_list(data.get("patterns")))
                    fams = data.get("families")
                    if isinstance(fams, list):
                        for fam in fams:
                            if isinstance(fam, dict):
                                found.extend(_as_list(fam.get("patterns")))
                else:
                    found.extend(_as_list(data))
                extra = [p for p in found if isinstance(p, str) and p]
            except ValueError:
                extra = []
                error = error or "unparseable"
        w = cls(extra)
        w.source_error = error
        w.source_set = source is not None
        return w

    def _hit(self, text: str) -> bool:
        if any(r.search(text) for r in self._re):
            return True
        if text.isascii():
            return False
        # a name split by a soft hyphen or a zero-width space still reads as the name once a
        # viewer drops those characters: test a copy without Unicode format characters too
        plain = "".join(ch for ch in text if unicodedata.category(ch) != "Cf")
        return plain != text and any(r.search(plain) for r in self._re)

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
