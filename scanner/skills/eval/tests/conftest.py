import os
import shutil
import sys
from pathlib import Path

import pytest

EVAL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EVAL_DIR))


def _find_bin(env_name: str, default: str) -> str | None:
    value = os.environ.get(env_name, default)
    return value if (Path(value).is_file() or shutil.which(value)) else None


@pytest.fixture(scope="session")
def cisco_bin():
    b = _find_bin("CISCO_BIN", "skill-scanner")
    if not b:
        pytest.skip("skill-scanner не найден (задайте CISCO_BIN)")
    return b


@pytest.fixture(scope="session")
def skillspector_bin():
    b = _find_bin("SKILLSPECTOR_BIN", "skillspector")
    if not b:
        pytest.skip("skillspector не найден (задайте SKILLSPECTOR_BIN)")
    return b


@pytest.fixture(scope="session")
def rules_dir():
    """Свои правила с собранным паком Cisco ($SKILLS_RULES_DIR, в образе -- /srv/rules)."""
    from engines import cisco_pack, yara_dir

    value = os.environ.get("SKILLS_RULES_DIR")
    if not (value and cisco_pack(Path(value)) and yara_dir(Path(value))):
        pytest.skip("свои правила не собраны (задайте SKILLS_RULES_DIR)")
    return Path(value)
