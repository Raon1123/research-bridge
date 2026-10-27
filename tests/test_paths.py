from __future__ import annotations

import os

import pytest

from rb_node.paths import PathPolicy, PolicyError


@pytest.fixture
def policy(tmp_path):
    (tmp_path / "lab" / "registry").mkdir(parents=True)
    (tmp_path / "lab" / "registry" / "HYPOTHESES.md").write_text("h")
    (tmp_path / "inbox").mkdir()
    return PathPolicy(tmp_path, ["lab", "inbox"], ["inbox"])


def test_read_inside_root(policy, tmp_path):
    p = policy.resolve_read("lab/registry/HYPOTHESES.md")
    assert p == (tmp_path / "lab" / "registry" / "HYPOTHESES.md").resolve()


def test_dotdot_escape_rejected(policy):
    with pytest.raises(PolicyError):
        policy.resolve_read("lab/registry/../../etc/passwd")


def test_absolute_rejected(policy):
    with pytest.raises(PolicyError):
        policy.resolve_read("/etc/passwd")


def test_symlink_escape_rejected(policy, tmp_path):
    outside = tmp_path.parent / (tmp_path.name + "_outside")
    outside.mkdir()
    (outside / "secret.txt").write_text("s")
    try:
        os.symlink(str(outside), str(tmp_path / "lab" / "link"))
    except (OSError, NotImplementedError, AttributeError):
        pytest.skip("symlink not available")
    with pytest.raises(PolicyError):
        policy.resolve_read("lab/link/secret.txt")


def test_write_to_read_only_root_rejected(policy):
    with pytest.raises(PolicyError):
        policy.resolve_write("lab/registry/new.md")


def test_write_to_write_root_ok(policy, tmp_path):
    assert policy.resolve_write("inbox/a.md") == (tmp_path / "inbox" / "a.md").resolve()


def test_nul_byte_rejected(policy):
    with pytest.raises(PolicyError):
        policy.resolve_read("lab/a\x00b")
    with pytest.raises(PolicyError):
        policy.resolve_write("inbox/a\x00b")


def test_sibling_prefix_not_contained(policy, tmp_path):
    (tmp_path / "lab2").mkdir()
    with pytest.raises(PolicyError):
        policy.resolve_read("lab2/x")
