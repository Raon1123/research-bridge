from __future__ import annotations

import json
import shutil
from pathlib import Path

from rb_node.withheld import FALLBACK_PATTERNS, Withheld


def test_name_hit_png():
    w = Withheld.load(None)
    assert w.name_hit("reports/figures/pp_ltf_a.png")
    assert not w.name_hit("reports/figures/other.png")


def test_exp013_seed_threshold():
    w = Withheld.load(None)
    assert not w.name_hit("EXP-013_seed1.json")
    assert w.name_hit("EXP-013_seed2.json")
    assert w.name_hit("EXP-013-run-seed_12.json")


def test_mask_text():
    w = Withheld.load(None)
    assert w.mask_text("a\nH108N-x result\nb") == ("a\n\nb", 1)
    assert w.mask_text("a\nb") == ("a\nb", 0)


def test_tex_content_denied(tmp_path):
    f = tmp_path / "note.tex"
    f.write_text("see cleanr1_run here", encoding="utf-8")
    assert Withheld.load(None).check_file(f) == "deny_content"


def test_clean_text_ok(tmp_path):
    f = tmp_path / "note.md"
    f.write_text("nothing here", encoding="utf-8")
    assert Withheld.load(None).check_file(f) == "ok"


def test_name_denied_whole(tmp_path):
    f = tmp_path / "pp_seedext_1.png"
    f.write_bytes(b"x")
    assert Withheld.load(None).check_file(f) == "deny_name"


def test_image_name_only(tmp_path):
    f = tmp_path / "fig.png"
    f.write_bytes(b"H108N")
    assert Withheld.load(None).check_file(f) == "ok"


def test_pdf_without_pdftotext(tmp_path, monkeypatch):
    f = tmp_path / "paper.pdf"
    f.write_bytes(b"%PDF-1.4")
    monkeypatch.setattr(shutil, "which", lambda name: None)
    assert Withheld.load(None).check_file(f) == "deny_unscannable"


def test_unknown_extension_unscannable(tmp_path):
    f = tmp_path / "blob.bin"
    f.write_bytes(b"x")
    assert Withheld.load(None).check_file(f) == "deny_unscannable"


def test_load_missing_file_uses_fallback():
    assert Withheld.load(Path("missing.json")).name_hit("pp_seedext_1")


def test_load_broken_or_empty_file_uses_fallback(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("- not: json\n", encoding="utf-8")
    empty = tmp_path / "empty.json"
    empty.write_text("[]", encoding="utf-8")
    for p in (bad, empty):
        assert Withheld.load(p).name_hit("pp_seedext_1")


def test_load_unions_file_patterns(tmp_path):
    for body in (["zzz_secret"], {"patterns": ["zzz_secret"]}):
        f = tmp_path / "w.json"
        f.write_text(json.dumps(body), encoding="utf-8")
        w = Withheld.load(f)
        assert w.name_hit("a/zzz_secret.csv")
        assert w.name_hit("pp_ltf_x")


def test_invalid_regex_in_file_ignored(tmp_path):
    f = tmp_path / "w.json"
    f.write_text(json.dumps(["(unclosed", "ok_pat"]), encoding="utf-8")
    w = Withheld.load(f)
    assert w.name_hit("ok_pat") and w.name_hit("H108N")


def test_fallback_not_empty():
    assert len(FALLBACK_PATTERNS) == 5


def test_load_family_patterns(tmp_path):
    src = tmp_path / "w.json"
    src.write_text(json.dumps({
        "exp_ids": ["EXP-013"],
        "exp_id_patterns": ["EXP-013"],
        "families": [
            {"name": "fig", "patterns": ["fig1_mlp_z_iter_k3_s2"]},
            {"name": "verdict", "patterns": ["falsified|refuted", ""]},
        ],
    }), encoding="utf-8")
    w = Withheld.load(src)
    bad = tmp_path / "a.md"
    bad.write_text("line\nthis was refuted\n", encoding="utf-8")
    good = tmp_path / "b.md"
    good.write_text("plain text EXP-013 seed1", encoding="utf-8")
    assert w.check_file(bad) == "deny_content"
    assert w.check_file(good) == "ok"
    assert w.name_hit("x/fig1_mlp_z_iter_k3_s2.png")
    assert "" not in w.patterns
