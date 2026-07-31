#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""估算可得数据量：翻页(单月总量) + 历史月(时间深度) + 榜单类型(广度)。"""
import json, sys, time
sys.stdout.reconfigure(encoding="utf-8")
from scrapling.fetchers import Fetcher

BASE = "https://www.dongchedi.com/motor/pc/car/rank_data"
HDR = {"Referer": "https://www.dongchedi.com/sales"}


def fetch(params):
    q = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"{BASE}?{q}"
    p = Fetcher.get(url, impersonate="chrome", timeout=30, headers=HDR)
    if p.status != 200 or not p.body:
        return None
    try:
        return json.loads(p.body.decode("utf-8", "replace"))
    except Exception:
        return None


def count_all_pages(month="", ne="1", rtype="11", cap=600):
    """翻页统计某条件下总记录数。"""
    offset, total, names = 0, 0, []
    while offset < cap:
        d = fetch({"aid": 1839, "app_name": "auto_web_pc", "count": 60, "offset": offset,
                   "month": month, "new_energy_type": ne, "rank_data_type": rtype,
                   "brand_id": "", "price": "", "manufacturer": "",
                   "outter_detail_type": "", "nation": 0})
        if not d or d.get("status") != 0:
            break
        lst = d["data"]["list"]
        total += len(lst)
        names += [x["series_name"] for x in lst]
        has_more = d["data"]["paging"].get("has_more")
        offset += 60
        time.sleep(0.4)
        if not has_more or not lst:
            break
    return total, names


print("=== A. 当月新能源销量榜 翻页总量 ===")
tot, names = count_all_pages(month="", ne="1", rtype="11")
print(f"  当月新能源在榜车系数 ≈ {tot}")
print(f"  样例: {names[:8]} ... {names[-5:] if len(names)>8 else ''}")

print("\n=== B. 历史月时间深度（逐月探） ===")
months = ["202504", "202503", "202502", "202501", "202412", "202410", "202407", "202401"]
hist = {}
for m in months:
    d = fetch({"aid": 1839, "app_name": "auto_web_pc", "count": 5, "offset": 0,
               "month": m, "new_energy_type": "1", "rank_data_type": "11",
               "brand_id": "", "price": "", "manufacturer": "", "outter_detail_type": "", "nation": 0})
    ok = bool(d and d.get("status") == 0 and d["data"]["list"])
    top = d["data"]["list"][0]["series_name"] if ok else None
    hist[m] = (ok, top)
    print(f"  month={m}: {'OK' if ok else 'X'}  top={top}")
    time.sleep(0.4)

print("\n=== C. 广度：不同 new_energy_type / rank_data_type ===")
for ne, label in [("0", "全部"), ("1", "纯电?"), ("2", "插混?"), ("3", "增程?")]:
    d = fetch({"aid": 1839, "app_name": "auto_web_pc", "count": 3, "offset": 0,
               "month": "", "new_energy_type": ne, "rank_data_type": "11",
               "brand_id": "", "price": "", "manufacturer": "", "outter_detail_type": "", "nation": 0})
    ok = bool(d and d.get("status") == 0 and d["data"]["list"])
    top = [x["series_name"] for x in d["data"]["list"][:3]] if ok else None
    print(f"  new_energy_type={ne}({label}): {'OK' if ok else 'X'} {top}")
    time.sleep(0.3)

# 估算
ok_months = sum(1 for v in hist.values() if v[0])
print("\n=== 估算 ===")
print(f"  单月车系 ≈ {tot}；历史月可得（抽样 {len(months)} 个月中 {ok_months} 个 OK）")
print(f"  若回溯 24 个月：销量事实行 ≈ {tot} × 24 ≈ {tot*24}")
print(f"  报价事实/口碑事实 同量级；车系维度 ≈ {tot}（去重后）")
