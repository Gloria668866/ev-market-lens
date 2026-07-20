"""懂车帝口碑/车系详情页采集脚本（补评分/级别/续航 + RAG 评论语料）。
数据源：懂车帝口碑页/车系详情页（Next.js SSR，<script id="__NEXT_DATA__"> 可取整页 JSON）
接口：GET https://www.dongchedi.com/auto/series/score/{series_id}
免登录，带 Referer 即可。

采集字段：
  - total_score        → fact_review.score（需 /100，404 分 → 4.04 分）
  - car_type            → dim_series.segment（级别：中型SUV 等）
  - recharge_mileage    → dim_series.endurance_km（续航上限）
  - review_list[]       → RAG 评论语料

用法：python data/crawl_koubei.py [--apply] [--export-rag]
  --apply      将采集结果写回 bi_demo.db（回填 dim_series + fact_review）
  --export-rag 导出评论语料到 data/rag_corpus/
依赖：scrapling（需专用 venv）
"""
import argparse
import json
import random
import sqlite3
import time
from pathlib import Path

API_BASE = "https://www.dongchedi.com/auto/series/score"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://www.dongchedi.com",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

OUT_DIR = Path(__file__).parent / "raw"
MANIFEST = OUT_DIR / "_koubei_manifest.json"
DB_FILE = Path(__file__).parent.parent / "bi_demo.db"
RAG_DIR = Path(__file__).parent / "rag_corpus"


def fetch_series_detail(series_id: int, page: "PlaywrightPage") -> dict | None:
    """取单个车系的口碑/详情页数据。"""
    url = f"{API_BASE}/{series_id}"
    try:
        resp = page.get(url)
        text = resp.body.decode("utf-8", errors="ignore")
        # 从 <script id="__NEXT_DATA__"> 抽取 JSON
        import re
        m = re.search(r'<script\s+id="__NEXT_DATA__"[^>]*>\s*({.*?})\s*</script>', text, re.DOTALL)
        if not m:
            print(f"    ⚠️  series_id={series_id}: 找不到 __NEXT_DATA__")
            return None
        raw = json.loads(m.group(1))
        props = raw.get("props", {}).get("pageProps", {})
        if not props:
            return None

        head = props.get("seriesHomeHead", {})
        rev_data = props.get("reviewListData", {})
        reviews = rev_data.get("review_list") or []

        score_val = head.get("total_score")  # 值×100，404=4.04
        if isinstance(score_val, (int, float)) and score_val > 10:
            score_val = score_val / 100

        endurance_km = None
        config = head.get("pc_config", {}) or {}
        rm = config.get("recharge_mileage", "")
        if rm and "-" in rm:
            endurance_km = int(rm.split("-")[-1].replace("km", "").strip()) if rm else None

        return {
            "series_id": series_id,
            "series_name": head.get("series_name", ""),
            "car_type": head.get("car_type", ""),
            "total_score": score_val,
            "recharge_mileage": rm,
            "endurance_km": endurance_km,
            "review_count": len(reviews),
            "reviews": [
                {
                    "content": r.get("content", "").strip(),
                    "user_name": r.get("user_name", ""),
                    "score": r.get("score", 0),
                }
                for r in reviews[:50]  # 每车系最多取50条
            ],
        }
    except Exception as e:
        print(f"    ❌  series_id={series_id}: {e}")
        return None


def get_all_series_ids() -> list[int]:
    """从 bi_demo.db 读取所有车系 ID。"""
    if not DB_FILE.exists():
        print(f"[warn]  分析库不存在：{DB_FILE}，返回空列表")
        return []
    conn = sqlite3.connect(str(DB_FILE))
    rows = conn.execute("SELECT series_id FROM dim_series ORDER BY series_id").fetchall()
    conn.close()
    return [r[0] for r in rows]


def apply_to_db(detail: dict):
    """回填 dim_series + fact_review 到 bi_demo.db。"""
    conn = sqlite3.connect(str(DB_FILE))
    sid = detail["series_id"]
    # dim_series: 补 segment 和 endurance_km
    if detail.get("car_type"):
        conn.execute("UPDATE dim_series SET segment=? WHERE series_id=? AND segment IS NULL",
                     (detail["car_type"], sid))
    if detail.get("endurance_km"):
        conn.execute("UPDATE dim_series SET endurance_km=? WHERE series_id=? AND endurance_km IS NULL",
                     (detail["endurance_km"], sid))
    # fact_review: 补评分
    if detail.get("total_score") is not None:
        conn.execute("UPDATE fact_review SET score=? WHERE series_id=? AND score IS NULL",
                     (detail["total_score"], sid))
    conn.commit()
    conn.close()


def export_rag_corpus(details: list[dict]):
    """导出评论为 RAG 语料 JSONL。"""
    RAG_DIR.mkdir(parents=True, exist_ok=True)
    out = RAG_DIR / "dongchedi_koubei_reviews.jsonl"
    count = 0
    with out.open("w", encoding="utf-8") as f:
        for d in details:
            for r in (d.get("reviews") or []):
                if r["content"].strip():
                    f.write(json.dumps({
                        "series_id": d["series_id"],
                        "series_name": d.get("series_name", ""),
                        "content": r["content"],
                        "user_score": r.get("score", 0),
                        "source": "dongchedi_koubei",
                    }, ensure_ascii=False) + "\n")
                    count += 1
    print(f"  RAG corpus exported: {count} reviews → {out}")


def run(series_ids: list[int], apply: bool = False, export: bool = False):
    try:
        from scrapling import Playwright
    except ImportError:
        raise SystemExit("scrapling 未安装，请用专用 venv 运行")

    ids = series_ids or get_all_series_ids()
    if not ids:
        print("[skip]  无车系 ID，请先跑 crawl_sales 获得数据")
        return

    print(f"计划采集：{len(ids)} 个车系\n")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # 加载已有 manifest（幂等继续）
    manifest = {}
    if MANIFEST.exists():
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    all_details = []

    with Playwright(headless=True) as p:
        page = p.new_page(headers=HEADERS)
        for i, sid in enumerate(ids):
            key = str(sid)
            if key in manifest and manifest[key].get("status") == "ok":
                all_details.append(manifest[key])
                continue
            label = f"[{i+1}/{len(ids)}]"
            print(f"  {label}  series_id={sid} ...", end=" ", flush=True)
            detail = fetch_series_detail(sid, page)
            if detail:
                all_details.append(detail)
                manifest[key] = detail | {"status": "ok"}
                print(f"✅ score={detail.get('total_score')}  type={detail.get('car_type','')}  reviews={detail['review_count']}")
                if apply:
                    apply_to_db(detail)
            else:
                manifest[key] = {"series_id": sid, "status": "failed"}
                print("❌ 取不到数据")
            # 写 manifest（逐条落盘，崩了也能续）
            MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            time.sleep(random.uniform(0.5, 1.5))

    ok = sum(1 for v in manifest.values() if v.get("status") == "ok")
    print(f"\n完成！{ok}/{len(ids)} 成功 → {MANIFEST}")

    if export:
        export_rag_corpus(all_details)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="懂车帝口碑/车系详情 采集")
    parser.add_argument("--apply", action="store_true", help="回填 bi_demo.db")
    parser.add_argument("--export-rag", action="store_true", help="导出 RAG 评论语料")
    args = parser.parse_args()
    run([], apply=args.apply, export=args.export_rag)
