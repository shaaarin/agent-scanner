"""Единый явный реестр сканеров платформы.

Каждая запись описывает один сервис-сканер: какой тип скана он выполняет,
к каким видам активов применим, где живёт (compose-сервис + URL из env) и
какие фазы он пишет в Scan.phase. Этим реестром пользуются и API
(`GET /scanners`, создание/запуск скана), и документация -- никаких
параллельных словарей с условиями по типам.

Контракт самого сканера не меняется: `GET /health`, `POST /run/{scan_id}`,
прогресс -- обратно в control-api. Дополнительно сканер отдаёт
`GET /schema` -- описание полей конфига для динамической формы UI
(см. `app/api/scanners.py`).
"""
import os
from dataclasses import dataclass
from typing import Callable, Optional

from app.models import ScanType


@dataclass(frozen=True)
class ScannerRegistration:
    """Одна запись реестра. `asset_kinds` -- виды активов (см.
    `AssetKind`), на которых этот сканер можно запускать. `requirements`
    -- какие свойства актива сканеру нужны (любое из): "code" -- исходники,
    "live" -- работающий сервис, "deployable" -- платформа сама поднимет
    сервис при скане. `validate_config` -- необязательный hook: принимает
    JSON-строку Scan.config, нормализует её и/или бросает HTTPException при
    невалидном конфиге."""

    type: ScanType
    name: str
    description: str
    service: str  # имя сервиса в docker-compose
    url_env: str
    url_default: str
    asset_kinds: tuple[str, ...]
    phases: tuple[str, ...]
    requirements: frozenset[str] = frozenset()
    validate_config: Optional[Callable[[str], None]] = None

    @property
    def url(self) -> str:
        return os.environ.get(self.url_env, self.url_default)

    def available_for(self, capabilities: set[str]) -> bool:
        return not self.requirements or bool(capabilities & self.requirements)


def _validate_mcp_config_hook(raw_config: str) -> None:
    # Локальный импорт: mcp_config тянет pydantic-схемы, а реестр читают
    # модули, которым они не нужны.
    from app.mcp_config import validate_mcp_config

    validate_mcp_config(raw_config)


REGISTRY: tuple[ScannerRegistration, ...] = (
    ScannerRegistration(
        requirements=frozenset({"live", "deployable"}),  # агент: remote или собранный платформой
        type=ScanType.DEEP_TEAM,
        name="[динамическое тестирование] DeepTeam",
        description="Запускает агента и проверяет его ответы атаками DeepTeam (red teaming) с моделью-судьёй.",
        service="scanner-deepteam",
        url_env="SCANNER_DEEPTEAM_URL",
        url_default="http://scanner-deepteam:8000",
        asset_kinds=("agent",),
        phases=("Инициализация", "Запуск агента", "Ожидание агента", "Тестирование", "Сохранение результатов", "Завершено"),
    ),
    ScannerRegistration(
        requirements=frozenset({"live", "deployable"}),  # агент: remote или собранный платформой
        type=ScanType.PYRIT_SCAN,
        name="[динамическое тестирование] PyRIT",
        description="Запускает агента и атакует его целями через Microsoft PyRIT: одиночные промпты с конвертерами, "
        "адверсариальный многораундовый red teaming и Crescendo; успешность атаки оценивает модель-судья.",
        service="scanner-pyrit",
        url_env="SCANNER_PYRIT_URL",
        url_default="http://scanner-pyrit:8000",
        asset_kinds=("agent",),
        phases=("Инициализация", "Запуск агента", "Ожидание агента", "Тестирование", "Сохранение результатов", "Завершено"),
    ),
    ScannerRegistration(
        requirements=frozenset({"code"}),  # анализу нужны исходники
        type=ScanType.CODE_SCAN,
        name="[статический анализ] Promptfoo",
        description="Клонирует репозиторий агента и отправляет код в облако Promptfoo на статический анализ безопасности. Агент не запускается.",
        service="scanner-promptfoo",
        url_env="SCANNER_PROMPTFOO_URL",
        url_default="http://scanner-promptfoo:8000",
        asset_kinds=("agent",),
        phases=("Инициализация", "Клонирование", "Анализ кода", "Сохранение результатов", "Завершено"),
    ),
    ScannerRegistration(
        requirements=frozenset({"code"}),  # анализу нужны исходники
        type=ScanType.AI_CODE_SCAN,
        name="[статический анализ] Semgrep (AI-код)",
        description="Клонирует репозиторий агента и прогоняет локальный Semgrep по правилам для AI/LLM-кода: инъекции в промпты, исполнение ответов модели, ключи в исходниках. Агент не запускается, код не покидает платформу.",
        service="scanner-semgrep",
        url_env="SCANNER_SEMGREP_URL",
        url_default="http://scanner-semgrep:8000",
        asset_kinds=("agent",),
        phases=("Инициализация", "Клонирование", "Анализ кода", "Сохранение результатов", "Завершено"),
    ),
    ScannerRegistration(
        requirements=frozenset({"deployable"}),  # инъекции ставит MITM-прокси -- нужен под платформы
        type=ScanType.INDIRECT_INJECTION,
        name="[динамическое тестирование] Косвенные инъекции",
        description="Подкладывает инъекции в результаты инструментов агента во время работы и проверяет, поддаётся ли агент.",
        service="scanner-indirect",
        url_env="SCANNER_INDIRECT_URL",
        url_default="http://scanner-indirect:8000",
        asset_kinds=("agent",),
        phases=("Инициализация", "Запуск агента", "Ожидание агента", "Базовый прогон", "Фаззинг", "Сохранение результатов", "Завершено"),
    ),
    ScannerRegistration(
        requirements=frozenset({"deployable"}),  # метку ставит MITM-прокси -- нужен под платформы
        type=ScanType.SYSTEM_PROMPT_LEAK,
        name="[динамическое тестирование] Утечка системного промпта",
        description="Вставляет метку в системное сообщение агента через прокси и проверяет, раскроет ли агент системный промпт.",
        service="scanner-sysleak",
        url_env="SCANNER_SYSLEAK_URL",
        url_default="http://scanner-sysleak:8000",
        asset_kinds=("agent",),
        phases=("Инициализация", "Запуск агента", "Ожидание агента", "Тестирование", "Сохранение результатов", "Завершено"),
    ),
    ScannerRegistration(
        requirements=frozenset({"code", "live"}),  # SAST по коду, движки каталога -- по живому серверу
        type=ScanType.MCP,
        name="[статический и динамический анализ] MCP",
        description="Статический и динамический анализ MCP-серверов: каталог инструментов, SAST, динамические проверки.",
        service="scanner-mcp",
        url_env="SCANNER_MCP_URL",
        url_default="http://scanner-mcp:8000",
        asset_kinds=("mcp",),
        phases=("Инициализация", "Проверка MCP", "Сохранение результатов", "Завершено"),
        validate_config=_validate_mcp_config_hook,
    ),
)

_BY_TYPE: dict[ScanType, ScannerRegistration] = {reg.type: reg for reg in REGISTRY}


def find(scan_type: ScanType) -> Optional[ScannerRegistration]:
    """Регистрация по типу скана (или None -- тип без сканера)."""
    return _BY_TYPE.get(scan_type)


def for_asset_kind(asset_kind: str) -> list[ScannerRegistration]:
    """Сканеры, применимые к активу данного вида."""
    return [reg for reg in REGISTRY if asset_kind in reg.asset_kinds]
