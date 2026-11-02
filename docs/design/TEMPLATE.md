# <title> — design

Date: YYYY-MM-DD · Status: draft · Author: <session or person> · Code: `<paths touched>` · Data: `<data paths, if any>`

Status history:
- YYYY-MM-DD draft

<!--
Copy to docs/design/YYYY-MM-DD-<slug>.md. Delete the comment blocks once filled.
Section order follows docs/superpowers/specs/2026-10-27-research-bridge-design.md.
Placeholders only for server facts (<NODE_HOST>, <NODE_USER>, ...). No withheld content, no experiment results.
-->

## 1. Intent

<!-- The problem in the user's terms. What is hard today and for whom. -->

## 2. Goals

- G1. <!-- One observable outcome per line. Each goal gets a row in §10 Verification. -->

## 3. Non-goals

- <!-- Things this change deliberately does not do. -->

## 4. Anti-goals (failure even if it works)

- <!-- Outcomes that count as failure even when the feature works. Start from research-bridge design §4:
     unauthorized read or write, withheld content leaving the node, a job submitted twice or without approval,
     agent text in manuscripts. Add any specific to this change. -->

## 5. Constraints

- <!-- Contract sections, AGENTS.md hard rules touched, platform limits, existing code to reuse. -->

## 6. Architecture

<!-- Diagram or short description. Name each process, which side it runs on, and the direction of every connection
     (hard rule 2: laptop to node only). -->

### 6.1 Interfaces

| Name | Kind (read / mutation (pending) / internal) | Notes |
|---|---|---|
| | | |

<!-- If the MCP tool set changes, say so here: hard rule 1 pins exactly ten tools and a test asserts the set. -->

## 7. Security

<!-- Keys, forced commands, path roots (hard rule 4), withheld handling (hard rule 3), audit fields (hard rule 6),
     threat model in scope and out of scope. -->

## 8. Data and ledger

<!-- New or changed record kinds and fields, where bodies are stored, what the session browser shows. -->

## 9. Scope of this phase

1. <!-- Ordered build steps. Mark steps the user runs (keys, ssh config, node1 commands). -->

## 10. Verification

| Goal / anti-goal | Check | Kind (unit test / live check / manual) | Status |
|---|---|---|---|
| G1 | `tests/test_<...>.py::<name>` | unit test | not run |

<!-- "Not verified" is an allowed status; give the reason. A change counts as fixed only after the same
     reproduction passes (AGENTS.md Conventions). -->

## 11. Decided by the user

- <!-- Only what the user said, with the date. -->

## 12. My calls (user to check)

- <!-- Every choice the author made without the user. -->

## 13. Decision log (while building)

| # | Ruling | Cost if wrong | Where recorded |
|---|---|---|---|
| 1 | | | <!-- ledger line, commit, or report --> |

## 14. Left to the builder

<!-- Details the design does not fix: framing, flags, field names beyond §8. -->

## 15. Open questions

- <!-- Questions for the user, each with the default the author will use if unanswered. -->
