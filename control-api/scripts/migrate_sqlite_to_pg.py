"""Одноразовый перенос данных control-api из SQLite в PostgreSQL.

Схема целевой базы уже поднята миграциями Alembic при старте control-api
(DATABASE_URL); скрипт читает строки из старого sqlite-файла и вставляет их
в PostgreSQL с сохранением id (последовательности выставляются следом).
Значения читаются через те же SQLModel-модели, что пишет приложение, поэтому
JSON-колонки (включая двойное кодирование Scan.config/results) и BLOB-ы
(MCPB-архивы, архивы skills) переносятся без преобразований.

Запуск (compose-сеть даёт доступ и к postgres, и к legacy-тому):
    docker compose run --rm \
      -v agent-scanner_control-api-data:/legacy:ro \
      control-api python scripts/migrate_sqlite_to_pg.py /legacy/control-api.db

Повторный запуск на непустой базе прерывается; --truncate очищает таблицы
(TRUNCATE ... RESTART IDENTITY CASCADE) и позволяет перелить данные заново.
"""

import argparse
import sys
from pathlib import Path

from sqlalchemy import insert, text
from sqlmodel import Session, create_engine, select

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import DATABASE_URL  # noqa: E402
from app.models import (  # noqa: E402
    AgentConfig,
    InjectionTrial,
    LLMModel,
    McpAsset,
    MCPArtifact,
    Scan,
    ScanLog,
    SkillAsset,
    TrafficEvent,
)

# Порядок вставки: ссылочные таблицы раньше ссылающихся (FK scan → agentconfig,
# scanlog/injectiontrial/trafficevent → scan).
COPY_ORDER = [
    LLMModel,
    AgentConfig,
    McpAsset,
    SkillAsset,
    MCPArtifact,
    Scan,
    ScanLog,
    InjectionTrial,
    TrafficEvent,
]


def table_counts(session: Session) -> dict[str, int]:
    return {
        model.__tablename__: session.execute(
            text(f"SELECT COUNT(*) FROM {model.__tablename__}")
        ).scalar_one()
        for model in COPY_ORDER
    }


def copy_table(src: Session, dst: Session, model, batch_size: int) -> int:
    table = model.__table__
    columns = [column.name for column in table.columns]
    total = 0
    last_id = 0
    while True:
        rows = src.exec(
            select(model).where(model.id > last_id).order_by(model.id).limit(batch_size)
        ).all()
        if not rows:
            break
        last_id = rows[-1].id
        payload = [{name: getattr(row, name) for name in columns} for row in rows]
        dst.execute(insert(table), payload)
        dst.commit()
        total += len(payload)
        print(f"  {table.name}: перенесено {total}")
    return total


def sync_sequences(dst: Session) -> None:
    for model in COPY_ORDER:
        table = model.__tablename__
        dst.execute(
            text(
                f"SELECT setval("
                f"pg_get_serial_sequence('{table}', 'id'), "
                f"COALESCE(MAX(id), 1), MAX(id) IS NOT NULL) FROM {table}"
            )
        )
    dst.commit()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("sqlite_path", help="Путь до старого sqlite-файла control-api")
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument(
        "--truncate",
        action="store_true",
        help="Очистить целевые таблицы перед переносом (для повторного запуска)",
    )
    args = parser.parse_args()

    if not Path(args.sqlite_path).is_file():
        print(f"Файл не найден: {args.sqlite_path}", file=sys.stderr)
        return 2

    # mode=ro: старый том — «только чтение», SQLite при открытии на запись
    # может создавать journal-файлы рядом с базой.
    sqlite_engine = create_engine(
        f"sqlite:///file:{args.sqlite_path}?mode=ro&uri=true"
    )
    pg_engine = create_engine(DATABASE_URL, pool_pre_ping=True)

    with Session(pg_engine) as dst:
        before = table_counts(dst)
        if any(before.values()) and not args.truncate:
            print(
                "Целевая база PostgreSQL не пуста:",
                ", ".join(f"{t}={n}" for t, n in before.items() if n),
                "\nПовторный перенос возможен с флагом --truncate.",
                file=sys.stderr,
            )
            return 1
        if args.truncate:
            names = ", ".join(model.__tablename__ for model in COPY_ORDER)
            dst.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))
            dst.commit()
            print("Целевые таблицы очищены")

        with Session(sqlite_engine) as src:
            for model in COPY_ORDER:
                copied = copy_table(src, dst, model, args.batch_size)
                print(f"{model.__tablename__}: {copied}")

        sync_sequences(dst)

        after = table_counts(dst)
        mismatch = []
        print("\nИтог (источник → приёмник):")
        for model in COPY_ORDER:
            table = model.__tablename__
            source_count = source_count_for(sqlite_engine, table)
            marker = "OK" if source_count == after[table] else "РАСХОЖДЕНИЕ"
            if source_count != after[table]:
                mismatch.append(table)
            print(f"  {table}: {source_count} → {after[table]} [{marker}]")

        if mismatch:
            print(f"\nНе совпали таблицы: {', '.join(mismatch)}", file=sys.stderr)
            return 1
        print("\nПеренос завершён.")
        return 0


def source_count_for(sqlite_engine, table: str) -> int:
    with sqlite_engine.connect() as conn:
        return conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one()


if __name__ == "__main__":
    sys.exit(main())
