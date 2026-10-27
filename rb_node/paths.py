"""Path policy: confine node file access to configured roots (stdlib only)."""
from __future__ import annotations

import os
from pathlib import Path
from typing import List


class PolicyError(Exception):
    pass


def _real(p: Path) -> str:
    return os.path.realpath(str(p))


def _inside(path: str, root: str) -> bool:
    try:
        return os.path.commonpath([path, root]) == root
    except ValueError:  # different drives
        return False


class PathPolicy:
    def __init__(self, base: Path, read_roots: List[str], write_roots: List[str]) -> None:
        self.base = Path(base)
        self._read = [self._root(r) for r in read_roots]
        self._write = [self._root(r) for r in write_roots]

    def _root(self, r: str) -> str:
        p = Path(r)
        return _real(p if p.is_absolute() else self.base / p)

    def _resolve(self, rel: str, roots: List[str]) -> Path:
        if not isinstance(rel, str) or "\x00" in rel:
            raise PolicyError("invalid path")
        if os.path.isabs(rel) or Path(rel).is_absolute() or rel.startswith(("/", "\\")):
            raise PolicyError("absolute paths are not allowed")
        real = _real(self.base / rel)
        if not any(_inside(real, root) for root in roots):
            raise PolicyError("path outside allowed roots: %s" % rel)
        return Path(real)

    def resolve_read(self, rel_or_abs: str) -> Path:
        return self._resolve(rel_or_abs, self._read)

    def resolve_write(self, rel: str) -> Path:
        return self._resolve(rel, self._write)
