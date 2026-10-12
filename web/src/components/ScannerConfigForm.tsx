import { useState } from "react";
import type { ScannerField, ScannerFieldOption } from "../api/types";

// Рендерит поля конфига сканера по схеме из GET /scanners (config_schema).
// Форма полностью управляемая: value -- собираемый объект конфига,
// onChange -- его обновление. Никакой специфики конкретных сканеров здесь
// нет: только словарь типов полей.

type ConfigValue = Record<string, unknown>;

function isMultiType(field: ScannerField): boolean {
  return field.type === "enum_multi" || field.type === "text_list";
}

export function initialConfig(fields: ScannerField[]): ConfigValue {
  const config: ConfigValue = {};
  for (const field of fields) {
    if (field.default !== undefined) {
      config[field.name] = field.default;
    } else if (isMultiType(field)) {
      config[field.name] = [];
    } else if (field.type === "integer") {
      config[field.name] = field.default ?? undefined;
    } else if (field.type === "boolean") {
      config[field.name] = false;
    } else {
      config[field.name] = "";
    }
  }
  return config;
}

function FieldLabel({ field }: { field: ScannerField }) {
  return (
    <label style={{ display: "block", marginBottom: "0.5rem" }}>
      {field.label}
      {field.required && <span style={{ color: "var(--danger)" }}> *</span>}
    </label>
  );
}

function HelpText({ text }: { text?: string }) {
  if (!text) return null;
  return (
    <p style={{ margin: "0.4rem 0 0", color: "var(--text-500)", fontSize: 12 }}>{text}</p>
  );
}

function optionKey(option: ScannerFieldOption, index: number): string {
  return `${String(option.value)}-${index}`;
}

function EnumMultiField({
  field,
  selected,
  onToggle,
}: {
  field: ScannerField;
  selected: string[];
  onToggle: (value: string) => void;
}) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))", gap: "0.3rem 1.2rem" }}>
      {(field.options ?? []).map((option, index) => {
        const disabled = option.available === false;
        return (
          <label key={optionKey(option, index)} style={{ display: "flex", gap: "0.5rem", alignItems: "flex-start", fontSize: 13, color: disabled ? "var(--text-500)" : undefined }}>
            <input
              type="checkbox"
              checked={selected.includes(String(option.value))}
              disabled={disabled}
              onChange={() => onToggle(String(option.value))}
              style={{ marginTop: 2 }}
            />
            <span>
              {option.label}
              {disabled && <span style={{ color: "var(--text-500)" }}> (недоступен)</span>}
              {disabled && option.reason && (
                <span style={{ display: "block", color: "var(--status-negative)", fontSize: 12 }}>{option.reason}</span>
              )}
              {option.description && (
                <span style={{ display: "block", color: "var(--text-500)", fontSize: 12 }}>{option.description}</span>
              )}
            </span>
          </label>
        );
      })}
    </div>
  );
}

// Поле типа "json": редактируется текстом, в конфиг попадает разобранный
// объект; пока текст невалиден -- в конфиге лежит сырая строка, которую
// отбракует серверная валидация с внятной ошибкой.
function JsonField({
  field,
  raw,
  onRawChange,
}: {
  field: ScannerField;
  raw: string;
  onRawChange: (raw: string) => void;
}) {
  return (
    <>
      <textarea
        className="input"
        rows={6}
        style={{ width: "100%", fontFamily: "monospace", resize: "vertical" }}
        value={raw}
        onChange={(e) => onRawChange(e.target.value)}
      />
      {raw.trim() !== "" && parseJsonSafe(raw) === undefined && (
        <p style={{ margin: "0.4rem 0 0", color: "var(--danger)", fontSize: 12 }}>Невалидный JSON</p>
      )}
      <HelpText text={field.help} />
    </>
  );
}

function parseJsonSafe(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return undefined;
  }
}

export function ScannerConfigForm({
  fields,
  value,
  onChange,
}: {
  fields: ScannerField[];
  value: ConfigValue;
  onChange: (next: ConfigValue) => void;
}) {
  const set = (name: string, fieldValue: unknown) => onChange({ ...value, [name]: fieldValue });

  // Сырой текст json-полей живёт локально: конфиг получает разобранный
  // объект, пока текст валиден.
  const [jsonDrafts, setJsonDrafts] = useState<Record<string, string>>({});
  const setJsonRaw = (field: ScannerField, raw: string) => {
    setJsonDrafts((prev) => ({ ...prev, [field.name]: raw }));
    const parsed = raw.trim() === "" ? field.default ?? [] : parseJsonSafe(raw);
    set(field.name, parsed === undefined ? raw : parsed);
  };
  const jsonRaw = (field: ScannerField): string => {
    if (field.name in jsonDrafts) return jsonDrafts[field.name];
    const current = value[field.name];
    return typeof current === "string" ? current : JSON.stringify(current ?? field.default ?? null, null, 2);
  };

  const toggleMulti = (field: ScannerField, optionValue: string) => {
    const current = Array.isArray(value[field.name]) ? (value[field.name] as string[]) : [];
    const next = current.includes(optionValue) ? current.filter((item) => item !== optionValue) : [...current, optionValue];
    set(field.name, next);
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "1.2rem" }}>
      {fields.map((field) => (
        <div key={field.name}>
          <FieldLabel field={field} />
          {field.type === "string" && (
            <input
              className="input"
              style={{ width: "100%" }}
              value={String(value[field.name] ?? "")}
              onChange={(e) => set(field.name, e.target.value)}
            />
          )}
          {field.type === "text" && (
            <textarea
              className="input"
              rows={3}
              style={{ width: "100%" }}
              value={String(value[field.name] ?? "")}
              onChange={(e) => set(field.name, e.target.value)}
            />
          )}
          {field.type === "text_list" && (
            <textarea
              className="input"
              rows={4}
              style={{ width: "100%" }}
              placeholder="По одному значению на строку"
              value={Array.isArray(value[field.name]) ? (value[field.name] as string[]).join("\n") : ""}
              onChange={(e) =>
                set(
                  field.name,
                  e.target.value
                    .split("\n")
                    .map((line) => line.trim())
                    .filter(Boolean),
                )
              }
            />
          )}
          {field.type === "integer" && (
            <input
              className="input"
              type="number"
              style={{ width: "100%" }}
              value={value[field.name] === undefined || value[field.name] === null ? "" : String(value[field.name])}
              onChange={(e) => set(field.name, e.target.value === "" ? undefined : Number(e.target.value))}
            />
          )}
          {field.type === "boolean" && (
            <label style={{ display: "flex", gap: "0.5rem", alignItems: "center", fontSize: 13 }}>
              <input
                type="checkbox"
                checked={Boolean(value[field.name])}
                onChange={(e) => set(field.name, e.target.checked)}
              />
              Включить
            </label>
          )}
          {field.type === "enum" && (
            <select
              className="input"
              style={{ width: "100%" }}
              value={value[field.name] === undefined || value[field.name] === null ? "" : String(value[field.name])}
              onChange={(e) => set(field.name, e.target.value === "" ? undefined : e.target.value)}
            >
              <option value="">—</option>
              {(field.options ?? []).map((option, index) => (
                <option key={optionKey(option, index)} value={String(option.value)}>
                  {option.label}
                </option>
              ))}
            </select>
          )}
          {field.type === "llm_model" && (
            <select
              className="input"
              style={{ width: "100%" }}
              value={value[field.name] === undefined || value[field.name] === null ? "" : String(value[field.name])}
              onChange={(e) => set(field.name, e.target.value === "" ? undefined : Number(e.target.value))}
            >
              <option value="">Выберите модель…</option>
              {(field.options ?? []).map((option, index) => (
                <option key={optionKey(option, index)} value={String(option.value)}>
                  {option.label}
                </option>
              ))}
            </select>
          )}
          {field.type === "enum_multi" && (
            <EnumMultiField
              field={field}
              selected={Array.isArray(value[field.name]) ? (value[field.name] as string[]).map(String) : []}
              onToggle={(optionValue) => toggleMulti(field, optionValue)}
            />
          )}
          {field.type === "json" && <JsonField field={field} raw={jsonRaw(field)} onRawChange={(raw) => setJsonRaw(field, raw)} />}
          {field.type !== "json" && <HelpText text={field.help} />}
        </div>
      ))}
    </div>
  );
}

// Проверка заполненности обязательных полей перед созданием скана.
export function isConfigComplete(fields: ScannerField[], value: ConfigValue): boolean {
  return fields.every((field) => {
    if (!field.required) return true;
    const current = value[field.name];
    if (isMultiType(field)) return Array.isArray(current) && current.length > 0;
    if (field.type === "integer" || field.type === "llm_model" || field.type === "enum") {
      return current !== undefined && current !== null && current !== "";
    }
    if (field.type === "json") return typeof current !== "string";
    if (field.type === "boolean") return true;
    return Boolean(String(current ?? "").trim());
  });
}

// Убираем пустые/незаполненные необязательные поля, чтобы бекенд применял
// свои дефолты, а конфиг скана не содержал мусора.
export function cleanConfig(fields: ScannerField[], value: ConfigValue): ConfigValue {
  const result: ConfigValue = {};
  for (const field of fields) {
    if (!(field.name in value)) continue;
    const current = value[field.name];
    if (isMultiType(field)) {
      if (Array.isArray(current) && current.length > 0) result[field.name] = current;
    } else if (field.type === "boolean") {
      if (current === true) result[field.name] = current;
    } else if (current !== undefined && current !== null && String(current) !== "") {
      result[field.name] = current;
    }
  }
  return result;
}
