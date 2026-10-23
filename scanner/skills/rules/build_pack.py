"""Сборка правил scanner-skills (D-18, D-35).

Один источник -- `rules/yara/*.yara`. Скрипт:
  * проверяет `meta` каждого правила: `description`, `severity`, `category`
    (категория -- из списка Cisco 2.1.0, иначе Cisco не стартует), имя
    правила начинается с `skills_` и не повторяется;
  * генерирует пак для Cisco `--trusted-rule-pack`: `<out>/pack.yaml` (schema
    v2, `description` совпадает с `meta`, иначе Cisco откажется стартовать) и
    копию `.yara` в `<out>/yara/`;
  * с `--compile yara_x|yara` компилирует каждый файл движком YARA из
    текущего окружения: при сборке образа -- YARA-X из venv Cisco и libyara из
    venv SkillSpector. Сломанное правило валит сборку, а не скан.

Только stdlib: скрипт запускается питоном любого venv образа. `pack.yaml`
пишется как JSON-совместимый YAML.

    python rules/build_pack.py --out rules/cisco-pack --compile yara_x
    python rules/build_pack.py --compile yara       # только проверка
"""
import argparse
import json
import re
import shutil
import sys
from pathlib import Path

RULES_DIR = Path(__file__).resolve().parent / "yara"
PACK_NAME = "agent-scanner-skills"
PACK_VERSION = "1.0.0"
RULE_PREFIX = "skills_"
SEVERITIES = ("CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO")
# skill_scanner.core.models.ThreatCategory, cisco-ai-skill-scanner 2.1.0.
CISCO_CATEGORIES = (
    "prompt_injection", "command_injection", "data_exfiltration", "unauthorized_tool_use",
    "obfuscation", "hardcoded_secrets", "social_engineering", "resource_abuse",
    "policy_violation", "malware", "harmful_content", "skill_discovery_abuse",
    "transitive_trust_abuse", "autonomy_abuse", "tool_chaining_abuse",
    "unicode_steganography", "supply_chain_attack",
)

_RULE_RE = re.compile(r"^\s*(?:private\s+|global\s+)*rule\s+([A-Za-z_][A-Za-z0-9_]*)[^{]*\{(.*?)^\s*condition\s*:", re.M | re.S)
_META_RE = re.compile(r"^\s*meta\s*:(.*?)(?=^\s*(?:strings|condition)\s*:)", re.M | re.S)
_PAIR_RE = re.compile(r'^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*"((?:[^"\\]|\\.)*)"\s*$', re.M)


class RuleError(ValueError):
    pass


def _strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S)
    return re.sub(r"(?m)//[^\n]*$", "", text)


def _unescape(value: str) -> str:
    return re.sub(r"\\(.)", r"\1", value)


def parse_rules(path: Path) -> list[dict]:
    """[{name, description, severity, category, file}] из одного .yara."""
    text = _strip_comments(path.read_text(encoding="utf-8"))
    rules = []
    for match in _RULE_RE.finditer(text):
        name, body = match.group(1), match.group(2)
        meta_match = _META_RE.search(body + "\ncondition:")
        meta = dict(_PAIR_RE.findall(meta_match.group(1))) if meta_match else {}
        rules.append(
            {
                "name": name,
                "description": _unescape(meta.get("description", "")),
                "severity": meta.get("severity", ""),
                "category": meta.get("category", ""),
                "file": path.name,
            }
        )
    if not rules:
        raise RuleError(f"{path.name}: не найдено ни одного правила")
    return rules


def validate(rules: list[dict]) -> None:
    errors = []
    seen: dict[str, str] = {}
    for rule in rules:
        where = f"{rule['file']}:{rule['name']}"
        if not rule["name"].startswith(RULE_PREFIX):
            errors.append(f"{where}: имя правила должно начинаться с {RULE_PREFIX}")
        if rule["name"] in seen:
            errors.append(f"{where}: правило уже объявлено в {seen[rule['name']]}")
        seen[rule["name"]] = rule["file"]
        if not rule["description"].strip():
            errors.append(f"{where}: нет meta.description")
        if rule["severity"] not in SEVERITIES:
            errors.append(f"{where}: meta.severity={rule['severity']!r}, ожидается одно из {', '.join(SEVERITIES)}")
        if rule["category"] not in CISCO_CATEGORIES:
            errors.append(f"{where}: meta.category={rule['category']!r} нет в списке категорий Cisco")
    if errors:
        raise RuleError("\n".join(errors))


def load(rules_dir: Path = RULES_DIR) -> tuple[list[Path], list[dict]]:
    files = sorted(rules_dir.glob("*.yara"))
    if not files:
        raise RuleError(f"в {rules_dir} нет .yara")
    rules = [rule for path in files for rule in parse_rules(path)]
    validate(rules)
    return files, rules


def pack_manifest(rules: list[dict]) -> dict:
    return {
        "schema_version": 2,
        "name": PACK_NAME,
        "version": PACK_VERSION,
        "author": "agent-scanner",
        "license": "Apache-2.0",
        "description": "Правила scanner-skills: пробелы движков по корпусу eval/ (D-18). Генерируется rules/build_pack.py, руками не править.",
        "rules": {
            f"YARA_{rule['name']}": {
                "source": "yara",
                "category": rule["category"],
                "severity": rule["severity"],
                "knobs": {"enabled": True},
                "description": rule["description"],
            }
            for rule in rules
        },
    }


def write_pack(files: list[Path], rules: list[dict], out: Path) -> None:
    if out.exists():
        shutil.rmtree(out)
    (out / "yara").mkdir(parents=True)
    for path in files:
        shutil.copy2(path, out / "yara" / path.name)
    header = "# Сгенерировано rules/build_pack.py из rules/yara/*.yara (D-35). Не править руками.\n"
    (out / "pack.yaml").write_text(header + json.dumps(pack_manifest(rules), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def compile_all(files: list[Path], engine: str) -> None:
    errors = []
    if engine == "yara_x":
        import yara_x

        for path in files:
            try:
                yara_x.compile(path.read_text(encoding="utf-8"))
            except Exception as exc:  # noqa: BLE001 -- любая ошибка компиляции
                errors.append(f"{path.name} (YARA-X): {exc}")
    elif engine == "yara":
        import yara

        for path in files:
            try:
                yara.compile(filepath=str(path))
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{path.name} (libyara): {exc}")
    else:
        raise RuleError(f"неизвестный движок компиляции: {engine}")
    if errors:
        raise RuleError("\n".join(errors))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rules", type=Path, default=RULES_DIR)
    parser.add_argument("--out", type=Path, help="куда записать пак для Cisco (--trusted-rule-pack)")
    parser.add_argument("--compile", choices=("yara_x", "yara"), action="append", default=[])
    args = parser.parse_args(argv)
    try:
        files, rules = load(args.rules)
        for engine in args.compile:
            compile_all(files, engine)
        if args.out:
            write_pack(files, rules, args.out)
    except RuleError as exc:
        print(f"Ошибка в правилах:\n{exc}", file=sys.stderr)
        return 1
    done = ", ".join(args.compile) or "без компиляции"
    print(f"Правил: {len(rules)} в {len(files)} файлах; проверено: {done}" + (f"; пак: {args.out}" if args.out else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
