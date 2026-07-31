from pathlib import Path

import pytest

import data.build_pg_kb as seed


def test_build_pg_kb_rejects_local_backend(monkeypatch):
    monkeypatch.setattr(seed, "RAG_BACKEND", "local")
    with pytest.raises(RuntimeError, match="RAG_BACKEND=pg"):
        seed.build()


def test_build_pg_kb_ingests_every_markdown_as_public(monkeypatch, tmp_path):
    (tmp_path / "01-a.md").write_text("A", encoding="utf-8")
    (tmp_path / "02-b.md").write_text("B", encoding="utf-8")
    calls = []

    def fake_ingest(**kwargs):
        calls.append(kwargs)
        return len(calls), 3

    monkeypatch.setattr(seed, "RAG_BACKEND", "pg")
    monkeypatch.setattr(seed, "SEED_DIR", Path(tmp_path))
    monkeypatch.setattr(seed, "ingest_text_as_document", fake_ingest)

    assert seed.build() == (2, 6)
    assert [call["filename"] for call in calls] == ["01-a.md", "02-b.md"]
    assert all(call["public"] and call["user_id"] == 0 for call in calls)
