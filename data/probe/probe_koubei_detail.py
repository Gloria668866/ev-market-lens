#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T(补) 探针：懂车帝「口碑评分/评论」与「车系详情(级别/动力/续航)」接口。

延续 data/probe/probe.py 范式：对候选接口/页面各打一枪，拿真实样本与字段，落 data/probe/。
策略：① 直接试一批候选 JSON 接口（看 status + 是否 JSON + 顶层 key）；
      ② 抓车系页/口碑页 HTML，扒出内嵌 JSON（__NEXT_DATA__/window.* ）并按关键词检索，
         反查真实接口路径与字段（页面里通常带 score/level/动力/续航 与 /motor/pc/... 接口）。
用 scrapling 专用 venv 运行。
"""
import json, os, re, sys, time, traceback
from datetime import datetime

OUT = os.path.dirname(os.path.abspath(__file__))
sys.stdout.reconfigure(encoding="utf-8")
from scrapling.fetchers import Fetcher

# 目标车系：Model Y(4363, 2768 口碑) / 小米SU7(6187) / 星愿(20154)
SID = 4363
HDR = {"Referer": f"https://www.dongchedi.com/auto/series/{SID}",
       "Origin": "https://www.dongchedi.com"}
AID = {"aid": 1839, "app_name": "auto_web_pc"}


def q(d):
    return "&".join(f"{k}={v}" for k, v in d.items())


def get(url, headers=None):
    try:
        pg = Fetcher.get(url, impersonate="chrome", timeout=30, headers=headers or HDR)
        raw = pg.body.decode("utf-8", "replace") if pg.body else ""
        return pg.status, raw, pg
    except Exception as e:
        traceback.print_exc()
        return -1, str(e), None


def try_json(label, url):
    print(f"\n=== [{label}] {url[:110]}")
    st, raw, pg = get(url)
    print(f"  status={st} len={len(raw)} head={raw[:160]!r}")
    try:
        data = json.loads(raw)
        print(f"  JSON OK top_keys={list(data.keys())[:12]}")
        return data
    except Exception:
        print("  not JSON")
        return None


report = {"time": datetime.now().isoformat(), "series_id": SID, "json_probe": {}, "html_probe": {}}

# ---------- A) 候选 JSON 接口 ----------
candidates = {
    # 口碑总评分（车系总分 + 分项）
    "series_all_score":      f"https://www.dongchedi.com/motor/pc/car/series/series_all_score?{q(AID)}&series_id={SID}",
    "koubei_score":          f"https://www.dongchedi.com/motor/pc/koubei/score?{q(AID)}&series_id={SID}",
    "series_score":          f"https://www.dongchedi.com/motor/pc/car/series/score?{q(AID)}&series_id={SID}",
    # 口碑列表（评论文本）
    "koubei_list":           f"https://www.dongchedi.com/motor/pc/koubei/list?{q(AID)}&series_id={SID}&offset=0&count=10",
    "koubei_series_list":    f"https://www.dongchedi.com/motor/pc/koubei/series_all_koubei_list?{q(AID)}&series_id={SID}&offset=0&count=10",
    "car_koubei_list":       f"https://www.dongchedi.com/motor/pc/car/koubei/list?{q(AID)}&series_id={SID}&offset=0&count=10",
    # 车系详情（级别/动力/续航）
    "series_detail":         f"https://www.dongchedi.com/motor/pc/car/series/series_detail?{q(AID)}&series_id={SID}",
    "series_basic":          f"https://www.dongchedi.com/motor/pc/car/series/get_basic_info?{q(AID)}&series_id={SID}",
    "series_all_sku":        f"https://www.dongchedi.com/motor/pc/car/series/get_series_all_sku?{q(AID)}&series_id={SID}",
    "series_filter":         f"https://www.dongchedi.com/motor/pc/car/series/series_filter_info?{q(AID)}&series_id={SID}",
    "series_param":          f"https://www.dongchedi.com/motor/pc/car/series/series_param?{q(AID)}&series_id={SID}",
}
for name, url in candidates.items():
    data = try_json(name, url)
    if data is not None:
        with open(os.path.join(OUT, f"probe_{name}.json"), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        report["json_probe"][name] = {"ok": True, "status0": data.get("status"),
                                       "top_keys": list(data.keys())[:12]}
    else:
        report["json_probe"][name] = {"ok": False}
    time.sleep(0.4)

# ---------- B) 抓 HTML 页，扒内嵌 JSON + 反查接口路径 ----------
pages = {
    "series_page": f"https://www.dongchedi.com/auto/series/{SID}",
    "koubei_page": f"https://www.dongchedi.com/auto/series/score/{SID}",
    "koubei_page2": f"https://www.dongchedi.com/auto/series/{SID}/koubei",
    "params_page": f"https://www.dongchedi.com/auto/params-carIds-x-{SID}",
}
KW = ["score", "评分", "level", "级别", "动力", "powertrain", "纯电", "续航", "endurance", "range_km", "battery"]
for name, url in pages.items():
    print(f"\n##### [HTML {name}] {url}")
    st, raw, pg = get(url, headers={"Referer": "https://www.dongchedi.com/"})
    print(f"  status={st} len={len(raw)}")
    if st != 200 or not raw:
        report["html_probe"][name] = {"ok": False, "status": st}
        continue
    fn = f"probe_{name}.html"
    with open(os.path.join(OUT, fn), "w", encoding="utf-8") as f:
        f.write(raw)
    # 反查 /motor/pc/ 接口路径
    apis = sorted(set(re.findall(r"/motor/pc/[\w/]+", raw)))
    # 反查内嵌 JSON 里出现的关键词上下文
    kw_hit = {k: len(re.findall(k, raw)) for k in KW}
    # __NEXT_DATA__ 或大段 JSON
    next_data = re.search(r'id="__NEXT_DATA__"[^>]*>(\{.*?\})</script>', raw, re.S)
    report["html_probe"][name] = {"ok": True, "apis": apis[:40], "kw_hit": kw_hit,
                                  "has_next_data": bool(next_data)}
    print(f"  APIs found: {apis[:25]}")
    print(f"  kw_hit: {kw_hit}  next_data={bool(next_data)}")
    time.sleep(0.5)

with open(os.path.join(OUT, "_probe_koubei_report.json"), "w", encoding="utf-8") as f:
    json.dump(report, f, ensure_ascii=False, indent=2)
print("\n==== DONE → _probe_koubei_report.json ====")
