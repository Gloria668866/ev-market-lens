"""Application-PG migration runner contracts without requiring Docker or PG."""
from pathlib import Path

import pytest

from deploy import migrate_app_pg


class _FakeConnection:
    def __init__(self, fail_on: str | None = None):
        self.fail_on = fail_on
        self.executed: list[str] = []
        self.commits = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def execute(self, sql: str):
        self.executed.append(sql)
        if self.fail_on and self.fail_on in sql:
            raise RuntimeError("database rejected migration")

    def commit(self):
        self.commits += 1


def _write(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def test_migrations_run_in_filename_order_and_preserve_multi_statement_sql(
    monkeypatch,
    tmp_path,
):
    _write(tmp_path / "002_second.sql", "ALTER TABLE b ADD COLUMN c int;")
    _write(
        tmp_path / "001_first.sql",
        "ALTER TABLE a ADD COLUMN b int;\nALTER TABLE a ADD COLUMN c int;",
    )
    connection = _FakeConnection()
    monkeypatch.setattr(migrate_app_pg, "MIGRATIONS", tmp_path)
    monkeypatch.setattr(
        migrate_app_pg.psycopg,
        "connect",
        lambda _url: connection,
    )

    applied = migrate_app_pg.migrate()

    assert applied == ["001_first.sql", "002_second.sql"]
    assert len(connection.executed) == 2
    assert connection.executed[0].count("ALTER TABLE") == 2
    assert connection.commits == 1


@pytest.mark.parametrize("with_empty_file", [False, True])
def test_missing_or_empty_migration_set_fails_closed(
    monkeypatch,
    tmp_path,
    with_empty_file,
):
    if with_empty_file:
        _write(tmp_path / "001_empty.sql", "\n")
    monkeypatch.setattr(migrate_app_pg, "MIGRATIONS", tmp_path)
    monkeypatch.setattr(
        migrate_app_pg.psycopg,
        "connect",
        lambda _url: pytest.fail("database must not be opened"),
    )

    with pytest.raises(RuntimeError, match="migration"):
        migrate_app_pg.migrate()


def test_database_error_propagates_and_prevents_commit(monkeypatch, tmp_path):
    _write(
        tmp_path / "001_ok.sql",
        "ALTER TABLE a ADD COLUMN IF NOT EXISTS b int;",
    )
    _write(tmp_path / "002_bad.sql", "BROKEN MIGRATION;")
    connection = _FakeConnection(fail_on="BROKEN")
    monkeypatch.setattr(migrate_app_pg, "MIGRATIONS", tmp_path)
    monkeypatch.setattr(
        migrate_app_pg.psycopg,
        "connect",
        lambda _url: connection,
    )

    with pytest.raises(RuntimeError, match="database rejected"):
        migrate_app_pg.migrate()

    assert connection.commits == 0
