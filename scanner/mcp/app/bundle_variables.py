"""MCPB substitutions, not shell expansion. Never read arbitrary worker env."""
import math
import re
from pathlib import Path


VARIABLE = re.compile(r"\$\{([^{}]+)\}")


class BundleVariables:
    def __init__(self, root: Path, manifest: dict, user_config: dict):
        root = root.resolve()
        # Paths belong to the disposable bundle, never the host user's home.
        self.builtins = {
            "__dirname": str(root), "HOME": str(root),
            "DESKTOP": str(root / "Desktop"), "DOCUMENTS": str(root / "Documents"),
            "DOWNLOADS": str(root / "Downloads"), "pathSeparator": "/", "/": "/",
        }
        if not isinstance(user_config, dict):
            raise ValueError("MCPB user_config должен быть объектом")
        definitions = manifest.get("user_config") or {}
        if not isinstance(definitions, dict):
            raise ValueError("Описание user_config в манифесте должно быть объектом")
        self.values = {}
        for key, definition in definitions.items():
            if not isinstance(definition, dict):
                raise ValueError(f"Некорректное описание настройки MCPB: {key}")
            if key in user_config:
                value = user_config[key]
            elif "default" in definition:
                default = definition["default"]
                value = ([self.default(v) for v in default] if isinstance(default, list)
                         else self.default(default))
            else:
                value = None
            if definition.get("required") and (value is None or value == "" or value == []):
                raise ValueError(f"Не задана обязательная настройка MCPB: {key}")
            self.values[key] = value
        self.values.update(user_config)

    def default(self, value):
        return self.render(value, builtins_only=True) if isinstance(value, str) else value

    @staticmethod
    def scalar(value, key):
        if isinstance(value, str):
            result = value
        elif isinstance(value, bool):
            result = "true" if value else "false"
        elif isinstance(value, (int, float)) and (not isinstance(value, float) or math.isfinite(value)):
            result = str(value)
        else:
            raise ValueError(f"Переменная MCPB {key}: ожидается строка, число или boolean")
        if "\x00" in result:
            raise ValueError(f"Переменная MCPB {key}: нулевой символ запрещён")
        return result
    def lookup(self, key, builtins_only=False):
        if key in self.builtins:
            return self.builtins[key]
        if not builtins_only and key.startswith("user_config."):
            name = key[len("user_config."):]
            if name in self.values and self.values[name] is not None:
                return self.values[name]
            raise ValueError(f"Не задана настройка MCPB: {name}")
        raise ValueError(f"Неподдерживаемая переменная MCPB: {key}")

    def render(self, template, *, builtins_only=False):
        if not isinstance(template, str) or "\x00" in template:
            raise ValueError("Шаблон MCPB должен быть строкой без нулевых символов")
        # One pass: a user's literal '${...}' is data, never another template.
        return VARIABLE.sub(lambda match: self.scalar(
            self.lookup(match[1], builtins_only), match[1]), template)

    def arguments(self, templates):
        if not isinstance(templates, list):
            raise ValueError("server.mcp_config.args должен быть массивом строк")
        result = []
        for template in templates:
            match = VARIABLE.fullmatch(template) if isinstance(template, str) else None
            value = self.lookup(match[1]) if match else None
            if isinstance(value, list):
                result.extend(self.scalar(item, match[1]) for item in value)
            else:
                result.append(self.render(template))
        return result
