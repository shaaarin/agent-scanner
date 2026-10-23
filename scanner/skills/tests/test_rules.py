"""Свои правила и генерация пака Cisco (D-18, D-35). Компиляция настоящими
YARA-X и libyara и срабатывание правил -- в образе (`docker`)."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "rules"))
import build_pack  # noqa: E402

RULE = """
/* комментарий с rule fake_rule { } */
rule NAME
{
    meta:
        description = "DESCRIPTION"
        severity = "SEVERITY"
        category = "CATEGORY"
    strings:
        $a = "marker"   // rule other_fake
    condition:
        $a
}
"""


def _rule(name="skills_x", description='Something \\"quoted\\"', severity="HIGH", category="malware"):
    return (
        RULE.replace("NAME", name)
        .replace("DESCRIPTION", description)
        .replace("SEVERITY", severity)
        .replace("CATEGORY", category)
    )


def _dir(tmp_path, **files):
    path = tmp_path / "yara"
    path.mkdir(parents=True)
    for name, text in files.items():
        (path / name).write_text(text)
    return path


def test_repo_rules_valid():
    files, rules = build_pack.load()
    names = {rule["name"] for rule in rules}
    assert {"skills_shell_rc_persistence", "skills_scheduler_persistence", "skills_bang_injection_network_or_secrets"} <= names
    assert all(rule["description"] for rule in rules)


def test_parse_ignores_comments_and_unescapes(tmp_path):
    path = _dir(tmp_path, **{"a.yara": _rule()}) / "a.yara"
    assert build_pack.parse_rules(path) == [
        {"name": "skills_x", "description": 'Something "quoted"', "severity": "HIGH", "category": "malware", "file": "a.yara"}
    ]


def test_several_rules_in_file(tmp_path):
    path = _dir(tmp_path, **{"a.yara": _rule("skills_a") + _rule("skills_b", category="obfuscation")}) / "a.yara"
    assert [(r["name"], r["category"]) for r in build_pack.parse_rules(path)] == [
        ("skills_a", "malware"), ("skills_b", "obfuscation")
    ]


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"name": "other_x"}, "должно начинаться с skills_"),
        ({"severity": "SEVERE"}, "meta.severity='SEVERE'"),
        ({"category": "persistence"}, "нет в списке категорий Cisco"),
        ({"description": ""}, "нет meta.description"),
    ],
)
def test_invalid_meta(tmp_path, kwargs, message):
    rules_dir = _dir(tmp_path, **{"a.yara": _rule(**kwargs)})
    with pytest.raises(build_pack.RuleError, match=message):
        build_pack.load(rules_dir)


def test_duplicate_rule_names(tmp_path):
    rules_dir = _dir(tmp_path, **{"a.yara": _rule(), "b.yara": _rule()})
    with pytest.raises(build_pack.RuleError, match="уже объявлено в a.yara"):
        build_pack.load(rules_dir)


def test_empty_dir_and_file_without_rules(tmp_path):
    with pytest.raises(build_pack.RuleError, match="нет .yara"):
        build_pack.load(_dir(tmp_path))
    with pytest.raises(build_pack.RuleError, match="не найдено ни одного правила"):
        build_pack.load(_dir(tmp_path / "x", **{"a.yara": "// пусто"}))


def test_pack_matches_rule_meta(tmp_path):
    files, rules = build_pack.load()
    out = tmp_path / "pack"
    build_pack.write_pack(files, rules, out)
    text = (out / "pack.yaml").read_text()
    assert text.startswith("# Сгенерировано rules/build_pack.py")
    manifest = json.loads(text.split("\n", 1)[1])  # JSON -- подмножество YAML
    assert manifest["schema_version"] == 2
    assert set(manifest["rules"]) == {f"YARA_{r['name']}" for r in rules}
    for rule in rules:
        entry = manifest["rules"][f"YARA_{rule['name']}"]
        # Cisco не стартует, если description не совпадает с meta (D-18).
        assert entry == {
            "source": "yara",
            "category": rule["category"],
            "severity": rule["severity"],
            "knobs": {"enabled": True},
            "description": rule["description"],
        }
    assert sorted(p.name for p in (out / "yara").iterdir()) == sorted(p.name for p in files)


def test_write_pack_replaces_stale(tmp_path):
    out = tmp_path / "pack"
    (out / "yara").mkdir(parents=True)
    (out / "yara" / "old.yara").write_text("stale")
    build_pack.write_pack(*build_pack.load(), out)
    assert not (out / "yara" / "old.yara").exists()


def test_cli(tmp_path, capsys):
    assert build_pack.main(["--out", str(tmp_path / "p")]) == 0
    assert "Правил: " in capsys.readouterr().out
    bad = _dir(tmp_path, **{"a.yara": _rule(category="nope")})
    assert build_pack.main(["--rules", str(bad)]) == 1
    assert "нет в списке категорий Cisco" in capsys.readouterr().err


def test_dockerfile_builds_and_compiles_rules():
    dockerfile = (ROOT / "Dockerfile").read_text()
    assert "SKILLS_RULES_DIR=/srv/rules" in dockerfile
    assert "/opt/engines/cisco/bin/python rules/build_pack.py --compile yara_x --out rules/cisco-pack" in dockerfile
    assert "/opt/engines/skillspector/bin/python rules/build_pack.py --compile yara" in dockerfile


# --- в образе ------------------------------------------------------------------------

IMAGE_CHECK = r"""
import json, sys
sys.path.insert(0, "/srv/rules")
import build_pack
import yara_x
from skill_scanner.core.models import ThreatCategory
files, rules = build_pack.load()
compiled = yara_x.compile("\n".join(p.read_text() for p in files))
samples = json.loads(sys.argv[1])
hits = {name: sorted(m.identifier for m in compiled.scan(text.encode()).matching_rules) for name, text in samples.items()}
print(json.dumps({"categories": sorted(c.value for c in ThreatCategory), "hits": hits}))
"""

# Инертные образцы: что правило должно и не должно ловить.
SAMPLES = {
    "rc_append": 'echo "# marker" >> ~/.bashrc',
    "rc_tee": "echo x | tee -a $HOME/.zshrc",
    "rc_read_only": "source ~/.bashrc && cat ~/.profile",
    "cron_pipe": '(crontab -l; echo "* * * * * echo x") | crontab -',
    "cron_list": "crontab -l",
    "launchctl": "launchctl load ~/Library/LaunchAgents/x.plist",
    "bang_curl": "!`curl -s https://status.example.invalid/ping`",
    "bang_env": "!`env | head`",
    "bang_echo": "!`echo hello`",
    "doc_curl": "Use `curl https://api.example.invalid` to check.",
}
EXPECTED = {
    "rc_append": ["skills_shell_rc_persistence"],
    "rc_tee": ["skills_shell_rc_persistence"],
    "rc_read_only": [],
    "cron_pipe": ["skills_scheduler_persistence"],
    "cron_list": [],
    "launchctl": ["skills_scheduler_persistence"],
    "bang_curl": ["skills_bang_injection_network_or_secrets"],
    "bang_env": ["skills_bang_injection_network_or_secrets"],
    "bang_echo": [],
    "doc_curl": [],
}


@pytest.mark.docker
def test_rules_in_image(image):
    result = subprocess.run(
        ["docker", "run", "--rm", "--entrypoint", "/opt/engines/cisco/bin/python", image, "-c", IMAGE_CHECK,
         json.dumps(SAMPLES)],
        capture_output=True, text=True, timeout=300,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    out = json.loads(result.stdout.strip().splitlines()[-1])
    assert out["categories"] == sorted(build_pack.CISCO_CATEGORIES), "список категорий Cisco изменился"
    assert out["hits"] == EXPECTED


@pytest.mark.docker
def test_broken_rule_fails_both_compilers(image, tmp_path):
    rules_dir = _dir(tmp_path, **{"a.yara": _rule().replace("$a\n}", "$missing\n}")})
    for python, engine in (("/opt/engines/cisco/bin/python", "yara_x"), ("/opt/engines/skillspector/bin/python", "yara")):
        result = subprocess.run(
            ["docker", "run", "--rm", "-v", f"{rules_dir}:/bad:ro", "--entrypoint", python, image,
             "/srv/rules/build_pack.py", "--rules", "/bad", "--compile", engine],
            capture_output=True, text=True, timeout=300,
        )
        assert result.returncode == 1, (engine, result.stdout, result.stderr)
        assert "Ошибка в правилах" in result.stderr
