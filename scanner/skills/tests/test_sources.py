"""Этап «Получение исходников»: поиск скиллов, лимиты, zip через control-api,
отказ архива и путь до runner (D-21, D-44, D-45, D-46)."""
import json
import os
import subprocess

import pytest

from app import repo, runner, sources
from app.context import Deadline, ScanContext

from conftest import make_zip, skill_md, zip_source


def _ctx(tmp_path, source, max_skills=50):
    workdir = tmp_path / "work"
    workdir.mkdir()
    logs = []
    ctx = ScanContext(
        scan_id=1,
        scan={},
        config={},
        engines=["cisco"],
        source=source,
        workdir=workdir,
        deadline=Deadline(600),
        engine_timeout=300,
        max_skills=max_skills,
        log=lambda message, **kw: logs.append((kw.get("level", "info"), message)),
    )
    return ctx, logs


# --- поиск скиллов -----------------------------------------------------------------------


def _tree(root, files: dict[str, str]):
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)


def test_find_skills_sorted_with_names(tmp_path):
    _tree(tmp_path, {"b/SKILL.md": skill_md("beta"), "a/SKILL.md": "без frontmatter", "docs/readme.md": "x"})
    skills = sources.find_skills(tmp_path)
    assert [(s["name"], s["path"]) for s in skills] == [("a", "a"), ("beta", "b")]
    assert skills[0]["dir"] == (tmp_path / "a").resolve()


def test_root_skill(tmp_path):
    _tree(tmp_path, {"SKILL.md": skill_md("root-skill"), "scripts/x.sh": "echo"})
    assert [(s["name"], s["path"]) for s in sources.find_skills(tmp_path)] == [("root-skill", ".")]


def test_root_skill_without_name(tmp_path):
    _tree(tmp_path, {"SKILL.md": "просто текст"})
    assert sources.find_skills(tmp_path)[0]["name"] == "skill"


def test_nested_skill_is_part_of_outer(tmp_path):
    _tree(tmp_path, {"outer/SKILL.md": skill_md("outer"), "outer/inner/SKILL.md": skill_md("inner")})
    assert [s["path"] for s in sources.find_skills(tmp_path)] == ["outer"]


def test_skip_dirs_and_symlinks(tmp_path):
    _tree(tmp_path, {".git/x/SKILL.md": "x", "node_modules/p/SKILL.md": "x", "real/SKILL.md": skill_md("real")})
    os.symlink(tmp_path / "real", tmp_path / "link-dir")
    (tmp_path / "fake").mkdir()
    os.symlink(tmp_path / "real" / "SKILL.md", tmp_path / "fake" / "SKILL.md")
    assert [s["path"] for s in sources.find_skills(tmp_path)] == ["real"]


@pytest.mark.parametrize(
    "text",
    [
        "---\nname: [unclosed\n---\n",
        "---\nname: x\n",  # нет закрывающего ---
        "---\n- a\n- b\n---\n",  # не словарь
        "---\nname: 42\n---\n",
        "---\nname: !!python/object/apply:os.system ['echo']\n---\n",  # safe_load не исполняет
    ],
)
def test_frontmatter_name_fallback(tmp_path, text):
    _tree(tmp_path, {"weird/SKILL.md": text})
    assert sources.find_skills(tmp_path)[0]["name"] == "weird"


def test_frontmatter_name_trimmed(tmp_path):
    _tree(tmp_path, {"s/SKILL.md": f"---\nname: '  {'n' * 300}  '\n---\n"})
    assert sources.find_skills(tmp_path)[0]["name"] == "n" * 200


# --- fetch: zip ------------------------------------------------------------------------------


def test_fetch_zip(api, tmp_path):
    content = make_zip({"pack/a/SKILL.md": skill_md("alpha"), "pack/b/SKILL.md": skill_md("beta")})
    api.archives[1] = content
    ctx, logs = _ctx(tmp_path, zip_source(content))
    sources.fetch(ctx)
    assert ctx.rejected is None
    assert [(s["name"], s["path"]) for s in ctx.skills] == [("alpha", "pack/a"), ("beta", "pack/b")]
    assert ctx.source_meta == {
        "kind": "zip",
        "asset_id": 1,
        "filename": "pack.zip",
        "sha256": zip_source(content)["archive_sha256"],
        "size_bytes": len(content),
    }
    assert not (ctx.workdir / "asset.zip").exists()
    assert any("sha256 совпадает" in m for _, m in logs)
    assert logs[-1] == ("success", "Найдено скиллов: 2: alpha (pack/a), beta (pack/b)")


def test_fetch_zip_sha_mismatch(api, tmp_path):
    api.archives[1] = make_zip({"a/SKILL.md": skill_md("a")})
    ctx, _ = _ctx(tmp_path, {**zip_source(b"other"), "asset_id": 1})
    with pytest.raises(RuntimeError, match="не совпадает со снимком"):
        sources.fetch(ctx)


def test_fetch_zip_asset_gone(api, tmp_path):
    ctx, _ = _ctx(tmp_path, zip_source(b"x", asset_id=9))
    with pytest.raises(RuntimeError, match="не найден"):
        sources.fetch(ctx)


def test_fetch_zip_too_big(api, tmp_path, monkeypatch):
    from app import archive

    monkeypatch.setattr(archive, "MAX_ARCHIVE_BYTES", 100)
    content = make_zip({"a/SKILL.md": skill_md("a") * 20})
    api.archives[1] = content
    ctx, _ = _ctx(tmp_path, zip_source(content))
    with pytest.raises(RuntimeError, match="архив больше"):
        sources.fetch(ctx)


def test_fetch_zip_rejected(api, tmp_path):
    content = make_zip({"a/SKILL.md": skill_md("a"), "../escape.txt": "x"})
    api.archives[1] = content
    ctx, logs = _ctx(tmp_path, zip_source(content))
    sources.fetch(ctx)
    assert ctx.rejected == {"reason": "zip_slip", "detail": "путь выходит за пределы архива: ../escape.txt"}
    assert ctx.skills == []
    assert logs[-1][0] == "error"


def test_fetch_no_skills(api, tmp_path):
    content = make_zip({"readme.md": "нет скиллов"})
    api.archives[1] = content
    ctx, _ = _ctx(tmp_path, zip_source(content))
    with pytest.raises(RuntimeError, match="ни одного SKILL.md"):
        sources.fetch(ctx)


def test_fetch_too_many_skills(api, tmp_path):
    content = make_zip({f"s{i}/SKILL.md": skill_md(f"s{i}") for i in range(4)})
    api.archives[1] = content
    ctx, _ = _ctx(tmp_path, zip_source(content), max_skills=3)
    with pytest.raises(RuntimeError, match="слишком много скиллов: 4, допустимо не больше 3"):
        sources.fetch(ctx)


def test_many_skills_log_truncated(api, tmp_path):
    content = make_zip({f"s{i:02d}/SKILL.md": skill_md(f"s{i:02d}") for i in range(12)})
    api.archives[1] = content
    ctx, logs = _ctx(tmp_path, zip_source(content))
    sources.fetch(ctx)
    assert logs[-1][1].endswith("и ещё 2")


# --- fetch: git ------------------------------------------------------------------------------


@pytest.fixture
def git_origin(tmp_path, monkeypatch):
    src = tmp_path / "origin"
    _tree(src, {"skills/one/SKILL.md": skill_md("one"), "skills/two/SKILL.md": skill_md("two")})
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    for args in (
        ["init", "-q", "-b", "main"],
        ["add", "-A"],
        ["-c", "user.email=t@example.invalid", "-c", "user.name=t", "commit", "-q", "-m", "init"],
    ):
        subprocess.run(["git", *args], cwd=src, check=True, capture_output=True, env=env)
    monkeypatch.setattr(repo, "ALLOWED_PROTOCOLS", "file")
    return src


def test_fetch_repository(git_origin, tmp_path):
    source = {"kind": "repository", "git_repo_url": f"file://{git_origin}", "git_ref": "main", "git_access_token": None}
    ctx, logs = _ctx(tmp_path, source)
    sources.fetch(ctx)
    assert [s["path"] for s in ctx.skills] == ["skills/one", "skills/two"]
    assert ctx.source_meta["kind"] == "repository" and len(ctx.source_meta["commit"]) == 40
    assert "git_access_token" not in ctx.source_meta
    assert any(m.startswith("Склонирован коммит") for _, m in logs)


def test_fetch_repository_too_big(git_origin, tmp_path, monkeypatch):
    from app import archive

    monkeypatch.setattr(archive, "MAX_FILES", 1)
    source = {"kind": "repository", "git_repo_url": f"file://{git_origin}", "git_ref": "main"}
    ctx, _ = _ctx(tmp_path, source)
    with pytest.raises(RuntimeError, match="репозиторий слишком большой"):
        sources.fetch(ctx)


# --- runner целиком ----------------------------------------------------------------------------


def test_runner_rejected_archive_completes_with_block(api):
    content = make_zip({"a/SKILL.md": skill_md("a"), "a/../../escape.txt": "x"})
    api.archives[1] = content
    api.add_scan(70, config=json.dumps({"source": zip_source(content)}))
    runner.run_scan(70)
    scan = api.scans[70]
    assert scan["status"] == "completed", scan["error"]
    results = json.loads(scan["results"])
    assert results["verdict"] == "block"
    assert results["complete"] is True
    assert results["rejected"]["reason"] == "zip_slip"
    assert results["skills"] == [] and results["engines"] == {}
    assert results["llm"] == {"enabled": False}
    assert results["summary"]["total"] == 0
    assert results["archive"]["sha256"] == zip_source(content)["archive_sha256"]
    assert results["archive"]["size_bytes"] == len(content)
    assert "Статический анализ" not in api.phases(70)
    assert api.phases(70)[-2:] == ["Сохранение результатов", "Завершено"]
    assert api.messages(70)[-1].startswith("Архив отклонён, вердикт block")


def test_runner_no_skills_fails(api):
    content = make_zip({"readme.md": "x"})
    api.archives[1] = content
    api.add_scan(71, config=json.dumps({"source": zip_source(content)}))
    runner.run_scan(71)
    assert api.scans[71]["status"] == "failed"
    assert "ни одного SKILL.md" in api.scans[71]["error"]
