### Task 12: Session-browser edges

**Files:**
- Create: `D:/raw/vault-primary/90_Claude/60_Tools/session-calendar/bridge_edges.py`
- Modify: `D:/raw/vault-primary/90_Claude/60_Tools/session-calendar/refresh.py` (add one step after `link`), and the agent-sequence renderer only if a new edge kind needs a label

**Interfaces:**
- Consumes: ledger lines (kind `message`, `reply`, `event`, `job`).
- Produces: `build_edges(ledger_path: Path) -> list[dict]` emitting the same edge shape `agent_graph.py` uses for SendMessage edges (read it; match field names), with `kind = "bridge"`, `peer = "<node>:<to_session or 'responder'>"`, timestamps, attachment count and total bytes. Metadata only: no `body`. Output merged into `cache/agents/<sid>.json` for the laptop `from_session`.

- [ ] **Step 1:** `ListAgents` check as in Task 11. Read `ISSUES.md` and `REPRODUCE.md` first.
- [ ] **Step 2:** Test `build_edges` on a fixture ledger: two edges, no `body` key anywhere in output.
- [ ] **Step 3:** Implement, run `refresh.py`, then `verify.py` → all PASS; open `/agents` for the session that sent a test message and see the bridge edge.
- [ ] **Step 4:** Commit test copy in repo `feat: session browser edges`.

