### Task 3: Withheld filter

**Files:**
- Create: `rb_node/withheld.py`, `tests/test_withheld.py`

**Interfaces:**
- Consumes: fact "withheld pattern source" from Task 0.
- Produces: `FALLBACK_PATTERNS: list[str]` (Global Constraints values); `class Withheld(patterns: list[str])` with `@classmethod load(source: Path | None) -> Withheld` (union of file patterns and fallback; missing/unparseable file → fallback only, never empty), `name_hit(path: str) -> bool`, `mask_text(text: str) -> tuple[str, int]` (blank each hit line to `""`, return count), `check_file(path: Path) -> str` returning one of `"ok"`, `"deny_name"`, `"deny_content"`, `"deny_unscannable"`. pdf: run `pdftotext -q <file> -` (timeout 30 s); if `pdftotext` missing → `"deny_unscannable"`. `.tex/.md/.txt/.csv/.json` scanned as text; `.png/.jpg/.svg` name-only.

- [ ] **Step 1:** Tests: `name_hit("reports/figures/pp_ltf_a.png")` True; `mask_text("a\nH108N-x result\nb")` → `("a\n\nb", 1)`; a `.tex` file containing `cleanr1_run` → `"deny_content"`; `.pdf` with `shutil.which` monkeypatched to None → `"deny_unscannable"`; `load(Path("missing.json"))` still hits `pp_seedext_1`.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS. Commit `feat(node): withheld filter`.

