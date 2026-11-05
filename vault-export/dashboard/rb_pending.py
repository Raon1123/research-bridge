"""8765 approval page for research-bridge pending jobs (ledger job metadata only).

Approval happens only here (loopback + CSRF token + the approval passphrase, which the node
checks) or via `rb approve`; never an MCP tool. The passphrase is passed through, never stored
or echoed.
"""
from __future__ import annotations

import hmac
import html
import secrets
import sys

RB_REPO = "D:/raw/Codes/research-bridge"
try:  # an importable rb_host (installed, or on the path in tests) wins over the fixed location
    import rb_host  # noqa: F401
except ImportError:
    if RB_REPO not in sys.path:
        sys.path.insert(0, RB_REPO)

from rb_host import jobs  # noqa: E402
from rb_host.client import RemoteError  # noqa: E402
from rb_host.config import HostConfig  # noqa: E402

CSRF_TOKEN = secrets.token_urlsafe(32)


def _ctx():
    try:
        cfg = jobs.load_cfg()
    except FileNotFoundError:  # no host.json yet: defaults (empty ledger, no nodes)
        cfg = HostConfig()
    return jobs.ledger_for(cfg), cfg


def _e(v) -> str:
    """Escape for HTML after stripping control characters a session may have put in the ledger."""
    return html.escape(jobs.clean(v), quote=True)


def _form(action: str, label: str, job_id: str) -> str:
    pw = ('<input type="password" name="passphrase" autocomplete="off" '
          'placeholder="approval passphrase" required>' if action == "approve" else "")
    return ('<form method="post" action="/rb/%s" style="display:inline">'
            '<input type="hidden" name="csrf" value="%s">'
            '<input type="hidden" name="job_id" value="%s">%s'
            '<button type="submit">%s</button></form>'
            % (action, _e(CSRF_TOKEN), _e(job_id), pw, label))


def render_pending(ledger) -> str:
    rows = []
    for r in ledger.pending_jobs():
        jid = r.get("id", "")
        gpus = r.get("gpus", "")
        if isinstance(gpus, (list, tuple)):
            gpus = ",".join(str(g) for g in gpus)
        if r.get("op") == "cancel":
            what = "CANCEL job %s (key %s)" % (jobs.clean(r.get("target_job_id")),
                                              jobs.clean(r.get("idempotency_key")))
            cfg = '<code>%s</code>' % _e(what)
        else:
            cfg = ('%s<br><small>config_path: <code>%s</code><br>config_sha256: <code>%s</code></small>'
                   % (_e(r.get("config_name", "")), _e(r.get("config_path", "")),
                      _e(jobs.clean(r.get("config_sha256", ""))[:12])))
        rows.append(
            "<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s %s</td></tr>"
            % (_e(jid), _e(r.get("node", "")), cfg, _e(gpus),
               _e(r.get("gpu_hours", "")), _e(r.get("note", "")),
               _form("approve", "Approve", jid), _form("reject", "Reject", jid)))
    body = "".join(rows) or '<tr><td colspan="7">No pending jobs.</td></tr>'
    return ('<!doctype html><html><head><meta charset="utf-8"><title>Pending jobs</title></head><body>'
            "<h1>Pending approval</h1><table border=\"1\" cellpadding=\"4\">"
            "<tr><th>job</th><th>node</th><th>config</th><th>gpus</th><th>gpu_hours</th>"
            "<th>note</th><th>action</th></tr>%s</table></body></html>" % body)


def handle_post(client_ip, form, token, action, host=None, origin=None):
    """host and origin are the request's Host and Origin headers (PM-03). A missing Host is
    refused; a missing Origin is allowed (same-origin form posts from some clients omit it)."""
    if client_ip != "127.0.0.1" or not jobs.host_allowed(host) or not jobs.origin_allowed(origin):
        return 403, "forbidden"
    sent = form.get("csrf")
    if not isinstance(sent, str) or not isinstance(token, str) \
            or not hmac.compare_digest(sent.encode("utf-8"), token.encode("utf-8")):
        return 403, "forbidden"
    if action not in ("approve", "reject"):
        return 400, "bad request"
    job_id = form.get("job_id")
    if not isinstance(job_id, str) or not job_id:
        return 400, "bad request"
    passphrase = form.get("passphrase")
    if action == "approve" and (not isinstance(passphrase, str) or not passphrase):
        return 400, "approval passphrase required"
    try:
        ledger, cfg = _ctx()
        if action == "approve":
            jobs.approve(ledger, cfg, job_id, passphrase)
        else:
            jobs.reject(ledger, job_id)
    except RemoteError as exc:
        code = jobs.clean(exc.code, 60)  # a short code from the node, never the passphrase
        if exc.code in jobs.REFUSED:
            return 403, "approval refused by the node: %s" % code
        return 500, "operation failed: %s" % code
    except Exception:
        return 500, "operation failed"
    return 200, "%s ok" % action


def handle_get(client_ip, host=None):
    if client_ip != "127.0.0.1" or not jobs.host_allowed(host):
        return 403, "forbidden"
    try:
        ledger, _cfg = _ctx()
        return 200, render_pending(ledger)
    except Exception:
        return 500, "research-bridge unavailable"
