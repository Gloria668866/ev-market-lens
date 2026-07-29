"""Apply idempotent application-database SQL migrations to existing PG volumes."""
from pathlib import Path

import psycopg

from app.config import RAG_DATABASE_URL


MIGRATIONS = Path(__file__).parent / "postgres" / "migrations"


def migrate() -> list[str]:
    paths = sorted(MIGRATIONS.glob("*.sql"))
    if not paths:
        raise RuntimeError(f"no SQL migrations found in {MIGRATIONS}")

    migrations: list[tuple[Path, str]] = []
    for path in paths:
        sql = path.read_text(encoding="utf-8").strip()
        if not sql:
            raise RuntimeError(f"empty SQL migration: {path.name}")
        migrations.append((path, sql))

    applied: list[str] = []
    with psycopg.connect(RAG_DATABASE_URL) as connection:
        # No parameters are passed: psycopg uses PostgreSQL's simple-query
        # protocol, which intentionally supports a migration file containing
        # several statements.  The surrounding connection transaction makes
        # the full migration set atomic; any error exits non-zero and Compose
        # blocks API/worker startup.
        for path, sql in migrations:
            connection.execute(sql)
            applied.append(path.name)
        connection.commit()
    return applied


if __name__ == "__main__":
    print({"applied": migrate()})
