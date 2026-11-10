"""Node self-diagnosis. Read only: never creates a directory and never writes an audit record."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from . import approval
from .config import NodeConfig
from .withheld import Withheld


def state(cfg: NodeConfig, withheld: Withheld) -> dict:
    """Booleans and counts for `hello` (design section 6.5). No path or pattern text."""
    try:
        verifier = approval._load(Path(cfg.approval_path)) is not None
    except Exception:  # unreadable path of any kind: report False, never raise
        verifier = False
    claude = cfg.claude_bin
    return {
        "configured": True,
        "approval_verifier": verifier,
        "job_template_set": bool(cfg.job_template),
        "withheld_source_set": bool(withheld.source_set),
        "withheld_loaded": withheld.extra_count,
        "withheld_rejected": withheld.rejected_count,
        "harness_root_set": bool(cfg.harness_root),
        "claude_bin_found": bool(claude) and os.path.isfile(claude) and os.access(claude, os.X_OK),
        "queue_dir_exists": os.path.isdir(cfg.queue_dir),
        "python": "%d.%d.%d" % sys.version_info[:3],
    }
