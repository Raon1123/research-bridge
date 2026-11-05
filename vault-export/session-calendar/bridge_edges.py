# -*- coding: utf-8 -*-
"""research-bridge 원장 -> 에이전트 시퀀스 곁자료의 "bridge" 연결.

원장(D:/raw/research-bridge/ledger.jsonl, 줄 단위 JSON, 같은 id 는 마지막 줄이 현재 값)에서
랩탑 세션과 서버 노드 사이의 메시지를 메타데이터만 뽑는다. 본문(body)은 읽어도 싣지 않는다.
세션이 확인되지 않는 레코드(보낸 쪽 세션이 없는 job 등)는 연결하지 않는다. 세션 id 를 지어내지 않는다.

merge() 는 cache/agents/<sid>.json 이 이미 있을 때만 거기에 합친다. 없으면 만들지 않고 건너뛴 수만 센다.
사용: python bridge_edges.py [ledger.jsonl]   (실패해도 종료 코드 0)
"""
from __future__ import annotations

import calendar
import json
import re
import sys
import time
from pathlib import Path

LEDGER = Path("D:/raw/research-bridge/ledger.jsonl")
CACHE = Path("D:/raw/session-calendar/cache/agents")
SID_RE = re.compile(r"[0-9a-f-]{36}")  # SEC-07: the session id becomes a file name
KINDS = ("message", "reply", "event", "job")


def _t(s):
    try:
        return float(calendar.timegm(time.strptime(s, "%Y-%m-%dT%H:%M:%SZ")))
    except (TypeError, ValueError):
        return None


def _records(path):
    latest = {}
    try:
        fh = open(str(path), "r", encoding="utf-8")
    except OSError:
        return []
    with fh:
        for line in fh:
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if isinstance(r, dict) and r.get("kind") in KINDS and "id" in r:
                latest[(r["kind"], r["id"])] = r
    return list(latest.values())


def _count(v):
    return len(v) if isinstance(v, list) else (v if isinstance(v, int) and not isinstance(v, bool) else 0)


def build_edges(ledger_path):
    recs = _records(ledger_path)
    sess_of = {r["id"]: r.get("from_session") for r in recs
               if r.get("direction") == "out" and r.get("from_session")}
    out = []
    for r in recs:
        node = r.get("node") or "node"
        peer = "%s:%s" % (node, r.get("to_session") or "responder")
        if r.get("direction") == "out":
            sid, outbound = r.get("from_session"), True
        else:
            ref = r.get("reply_to") or r.get("msg_id")
            sid, outbound = r.get("from_session") or sess_of.get(ref), False
        t = _t(r.get("created"))
        if not sid or t is None:
            continue
        lane = "ext:" + peer
        att = r.get("attachments") if outbound else r.get("files")
        out.append({"kind": "bridge", "from": "main" if outbound else lane,
                    "to": lane if outbound else "main", "t": t,
                    "err": r.get("status") in ("failed", "responder_failed"),
                    "msgtype": r.get("msg_kind") or r.get("op") or r.get("kind"),
                    "sid": sid, "peer": peer, "msg_id": r["id"],
                    "attachments": _count(att),
                    "bytes": _count(r.get("attachment_bytes")),
                    "status": r.get("status")})
    out.sort(key=lambda e: e["t"])
    return out


def merge(edges, cache_dir=CACHE):
    cache_dir = Path(cache_dir)
    by = {}
    for e in edges:
        by.setdefault(e["sid"], []).append(e)
    merged = skipped = 0
    for sid, es in by.items():
        if not isinstance(sid, str) or not SID_RE.fullmatch(sid):
            skipped += len(es)  # never build a path from a ledger-supplied id
            continue
        p = cache_dir / (sid + ".json")
        if not p.is_file():
            skipped += len(es)
            continue
        g = json.loads(p.read_text(encoding="utf-8"))
        g["events"] = [x for x in g.get("events", []) if x.get("kind") != "bridge"]
        lanes = g.setdefault("lanes", [])
        for e in es:
            g["events"].append({k: v for k, v in e.items() if k != "sid"})
            if not any(l.get("id") == e["to" if e["to"] != "main" else "from"] for l in lanes):
                lid = e["to"] if e["to"] != "main" else e["from"]
                lanes.append({"id": lid, "kind": "external", "label": lid[4:], "via": "bridge",
                              "parent": None, "t0": None, "t1": None,
                              "tools": 0, "in_tok": 0, "out_tok": 0})
        g["events"].sort(key=lambda x: x.get("t") or 0)
        g.setdefault("counts", {})["bridge"] = len(es)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(g, ensure_ascii=False), encoding="utf-8", newline="\n")
        tmp.replace(p)
        merged += len(es)
    return {"merged": merged, "skipped": skipped}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    edges = build_edges(Path(argv[0]) if argv else LEDGER)
    res = merge(edges)
    print("bridge_edges: edges %d merged %d skipped %d" % (len(edges), res["merged"], res["skipped"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
