"""招聘者入口与仓库单一事实源门禁。"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_deprecated_duplicate_entrypoints_are_absent():
    deprecated = [
        "phone/package.json",
        "phone/src/App.vue",
        "data/api_demo.py",
        "data/graph_demo.py",
        "data/rag_build_kb.py",
        "data/rag_eval/eval_report.json",
        "data/rag_eval/eval_set.jsonl",
        "data/rag_eval_build.py",
        "data/rag_eval_run.py",
        "data/rag_fts_backfill.py",
        "data/rag_ingest_demo.py",
        "data/crawl_seed_corpus.py",
        "data/export_rag_corpus.py",
        "data/probe/volume_probe.py",
        "data/probe/probe_koubei_detail.py",
        "data/probe/口碑车系详情字段清单.md",
        "frontend/src/layouts/MobileLayout.vue",
        "frontend/src/views/MobileChat.vue",
        "frontend/src/views/MobileHome.vue",
        "frontend/src/composables/useHotkeys.js",
        "frontend/src/composables/useIsMobile.js",
    ]

    present = [path for path in deprecated if (ROOT / path).exists()]
    assert not present, f"旧入口会与权威实现/评测口径冲突: {present}"


def test_agent_entrypoint_contains_no_private_or_stale_context():
    content = (ROOT / "AGENTS.md").read_text(encoding="utf-8")

    assert "<claude-mem-context>" not in content
    assert r"C:\Users\Lenovo" not in content
    assert "DeepSeek-V4" not in content
    assert "MinerU 解析" not in content
    assert "Scrapling 爬虫" not in content
    assert "PARSER_BACKEND=lite" in content
    assert "五类意图" in content
