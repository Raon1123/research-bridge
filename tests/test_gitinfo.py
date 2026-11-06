import subprocess

from rb_node import gitinfo
from rb_node.withheld import Withheld


def _repo(p):
    for a in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"],
              ["commit", "-q", "--allow-empty", "-m", "secret subject"]):
        subprocess.run(["git", "-C", str(p)] + a, check=True)
    return p


def test_state_has_no_names_or_subjects(tmp_path):
    r = _repo(tmp_path)
    (r / "pp_seedext.txt").write_text("x")
    st = gitinfo.repo_state(r)
    assert st["available"] and len(st["head"]) == 40 and st["dirty_files"] == 1
    assert "pp_seedext" not in str(st) and "secret subject" not in str(st)


def test_not_a_repo(tmp_path):
    assert gitinfo.repo_state(tmp_path) == {"available": False}


def test_branch_masked_and_origin_cleaned(tmp_path):
    r = _repo(tmp_path)
    subprocess.run(["git", "-C", str(r), "checkout", "-q", "-b", "cleanr1_x"], check=True)
    subprocess.run(["git", "-C", str(r), "remote", "add", "origin", "https://u:tok@h.example/r"], check=True)
    st = gitinfo.mask_state(gitinfo.repo_state(r), Withheld.load(None))
    assert st["branch"] == "[withheld]" and "tok" not in st["origin"]


def test_install_record(tmp_path):
    r = _repo(tmp_path / "src") if (tmp_path / "src").mkdir() is None else None
    rec = gitinfo.write_install(tmp_path / "rb", r, "9.9")
    assert gitinfo.read_install(tmp_path / "rb")["version"] == "9.9" and rec["source"]["available"]


def test_read_doc_ids_use_configured_paths(tmp_path):
    import json
    from rb_node.config import NodeConfig
    from rb_node.remote import Node
    (tmp_path / "x" / "exp").mkdir(parents=True)
    (tmp_path / "x" / "exp" / "EXP-001_slug.md").write_text("hello")
    (tmp_path / "x" / "H.md").write_text("# H-001 title\nbody\n")
    cfg = NodeConfig(trm_root=str(tmp_path), read_roots=["x/"], write_roots=[],
                     experiments_dir="x/exp", hypotheses_path="x/H.md",
                     mailbox_root=str(tmp_path / "mb"), audit_path=str(tmp_path / "a.jsonl"),
                     withheld_source=None)
    n = Node(cfg)
    assert n.read_doc({"id": "EXP-001"})["text"] == "hello"
    assert "H-001" in n.read_doc({"id": "H-001"})["text"]
