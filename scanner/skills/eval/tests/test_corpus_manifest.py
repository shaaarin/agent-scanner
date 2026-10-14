"""Манифест корпуса согласован с диском и не содержит мусора."""
import json
from pathlib import Path

import pytest
import yaml

import build_manifest
from corpus import CORPUS_DIR, LABELS, MANIFEST, Case, external_cases, find_skill_dirs, load_manifest


def test_manifest_matches_disk():
    """manifest.yaml == результат build_manifest на текущем corpus/ (иначе забыли пересобрать)."""
    on_disk = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    assert on_disk == build_manifest.build()


def test_every_case_has_skill_md_and_valid_label():
    cases = load_manifest()
    assert len(cases) >= 30
    for c in cases:
        assert (c.path / "SKILL.md").is_file(), c.id
        assert c.label in LABELS
        assert c.technique and c.source


def test_all_skill_dirs_are_in_manifest():
    ids = {c.id for c in load_manifest()}
    on_disk = {d.relative_to(CORPUS_DIR).as_posix() for d in find_skill_dirs(CORPUS_DIR)}
    assert on_disk == ids


def test_corpus_has_all_three_label_kinds_and_marker_gaps():
    cases = {c.id: c for c in load_manifest()}
    assert {c.label for c in cases.values()} == LABELS
    techniques = {c.technique for c in cases.values()}
    assert {"claude-code-hooks", "shell-persistence", "claude-code-bang-injection"} <= techniques


def test_cisco_labels_follow_expected_json():
    for c in load_manifest():
        if c.id.startswith("cisco/"):
            exp = json.loads((c.path / "_expected.json").read_text(encoding="utf-8"))
            mapped = {"malicious": "malicious", "benign": "benign", "contextual_risk": "contextual"}
            assert c.label == mapped[exp["package_label"]], c.id


def test_unknown_label_rejected(tmp_path):
    m = tmp_path / "m.yaml"
    m.write_text("cases:\n- {id: a, path: a, label: evil, technique: t, source: s}\n")
    with pytest.raises(ValueError, match="неизвестная метка"):
        load_manifest(m, tmp_path)


def test_duplicate_ids_rejected(tmp_path):
    m = tmp_path / "m.yaml"
    row = "{id: a, path: a, label: benign, technique: t, source: s}"
    m.write_text(f"cases:\n- {row}\n- {row}\n")
    with pytest.raises(ValueError, match="повторяющиеся"):
        load_manifest(m, tmp_path)


def test_external_cases_discovers_skill_dirs(tmp_path):
    (tmp_path / "skills" / "a").mkdir(parents=True)
    (tmp_path / "skills" / "a" / "SKILL.md").write_text("---\nname: a\n---\n")
    (tmp_path / "skills" / "not-a-skill").mkdir()
    cases = external_cases(tmp_path)
    assert [c.id for c in cases] == ["anthropic/a"] and cases[0].label == "benign"
    assert external_cases(tmp_path / "missing") == []


def test_marker_fixtures_are_inert():
    """Маркерные фикстуры не должны содержать сетевых вызовов и реальных хостов."""
    forbidden = ("curl", "wget", "http://", "https://", "nc ", "/dev/tcp")
    for p in (CORPUS_DIR / "marker").rglob("*"):
        if p.is_file():
            text = p.read_text(encoding="utf-8")
            assert not any(tok in text for tok in forbidden), f"{p}: сетевой вызов в маркерной фикстуре"


def test_no_binary_or_av_test_files_in_corpus():
    for p in CORPUS_DIR.rglob("*"):
        if p.is_file():
            assert p.suffix.lower() not in {".bin", ".exe", ".dll", ".so", ".zip"}, p
            assert b"EICAR" not in p.read_bytes(), p
