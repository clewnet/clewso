"""Tests for compute_changeset() using real temporary git repos."""

import os
from pathlib import Path

import git
import pytest
from clewso_ingestion.diff import compute_changeset


@pytest.fixture(autouse=False)
def _clean_git_env(monkeypatch):
    """Remove GIT_DIR/GIT_WORK_TREE so GitPython uses the test repo, not the outer worktree."""
    monkeypatch.delenv("GIT_DIR", raising=False)
    monkeypatch.delenv("GIT_WORK_TREE", raising=False)


@pytest.fixture
def tmp_repo(tmp_path: Path, _clean_git_env) -> git.Repo:
    """Create a temporary git repo with an initial commit."""
    repo = git.Repo.init(str(tmp_path))
    repo.config_writer().set_value("user", "name", "Test").release()
    repo.config_writer().set_value("user", "email", "test@test.com").release()

    # Initial commit with a file
    readme = tmp_path / "README.md"
    readme.write_text("# Hello")
    repo.index.add(["README.md"])
    repo.index.commit("initial commit")
    return repo


def test_added_files(tmp_repo: git.Repo):
    base_sha = tmp_repo.head.commit.hexsha

    new_file = Path(tmp_repo.working_dir) / "new.py"
    new_file.write_text("print('hello')")
    tmp_repo.index.add(["new.py"])
    tmp_repo.index.commit("add new.py")

    cs = compute_changeset("test/repo", tmp_repo.working_dir, base_sha)

    assert "new.py" in cs.added
    assert cs.modified == []
    assert cs.removed == []


def test_removed_files(tmp_repo: git.Repo):
    base_sha = tmp_repo.head.commit.hexsha

    readme = Path(tmp_repo.working_dir) / "README.md"
    readme.unlink()
    tmp_repo.index.remove(["README.md"])
    tmp_repo.index.commit("remove README")

    cs = compute_changeset("test/repo", tmp_repo.working_dir, base_sha)

    assert "README.md" in cs.removed
    assert cs.added == []
    assert cs.modified == []


def test_modified_files(tmp_repo: git.Repo):
    base_sha = tmp_repo.head.commit.hexsha

    readme = Path(tmp_repo.working_dir) / "README.md"
    readme.write_text("# Updated content")
    tmp_repo.index.add(["README.md"])
    tmp_repo.index.commit("modify README")

    cs = compute_changeset("test/repo", tmp_repo.working_dir, base_sha)

    assert "README.md" in cs.modified
    assert cs.added == []
    assert cs.removed == []


def test_renamed_files(tmp_repo: git.Repo):
    base_sha = tmp_repo.head.commit.hexsha

    old_path = Path(tmp_repo.working_dir) / "README.md"
    new_path = Path(tmp_repo.working_dir) / "DOCS.md"
    os.rename(old_path, new_path)
    tmp_repo.index.remove(["README.md"])
    tmp_repo.index.add(["DOCS.md"])
    tmp_repo.index.commit("rename README to DOCS")

    cs = compute_changeset("test/repo", tmp_repo.working_dir, base_sha)

    # Rename decomposes into remove(old) + add(new)
    assert "README.md" in cs.removed
    assert "DOCS.md" in cs.added


def test_no_changes(tmp_repo: git.Repo):
    base_sha = tmp_repo.head.commit.hexsha

    cs = compute_changeset("test/repo", tmp_repo.working_dir, base_sha)

    assert cs.added == []
    assert cs.modified == []
    assert cs.removed == []


def test_commit_sha_set_to_head(tmp_repo: git.Repo):
    base_sha = tmp_repo.head.commit.hexsha

    new_file = Path(tmp_repo.working_dir) / "foo.py"
    new_file.write_text("x = 1")
    tmp_repo.index.add(["foo.py"])
    tmp_repo.index.commit("add foo")

    cs = compute_changeset("test/repo", tmp_repo.working_dir, base_sha)

    assert cs.commit_sha == tmp_repo.head.commit.hexsha
    assert cs.repo_id == "test/repo"
    assert cs.repo_path == tmp_repo.working_dir


def test_explicit_to_sha(tmp_repo: git.Repo):
    base_sha = tmp_repo.head.commit.hexsha

    # Create two commits, target the first one
    f1 = Path(tmp_repo.working_dir) / "a.py"
    f1.write_text("a")
    tmp_repo.index.add(["a.py"])
    mid_commit = tmp_repo.index.commit("add a")

    f2 = Path(tmp_repo.working_dir) / "b.py"
    f2.write_text("b")
    tmp_repo.index.add(["b.py"])
    tmp_repo.index.commit("add b")

    cs = compute_changeset("test/repo", tmp_repo.working_dir, base_sha, mid_commit.hexsha)

    assert "a.py" in cs.added
    assert "b.py" not in cs.added
    assert cs.commit_sha == mid_commit.hexsha
