"""生成样例业务库（默认 SQLite: bi_demo.db）。
运行: python seed.py
表结构对齐 PRD §1.5：区域/车型/经销商 维度 + 销售/售后 事实 + 报告文档。
"""
import random
from datetime import date, timedelta
from sqlalchemy import create_engine, text
from app.config import DATABASE_URL

random.seed(42)
engine = create_engine(DATABASE_URL, future=True)

REGIONS = [(1, "华北"), (2, "华东"), (3, "华南"), (4, "西南"), (5, "东北")]
MODELS = [(1, "C级", "轿车"), (2, "E级", "轿车"), (3, "GLC", "SUV"),
          (4, "GLE", "SUV"), (5, "A级", "轿车")]
AFTER_TYPES = ["保养", "维修", "召回", "质保"]

DDL = [
    "DROP TABLE IF EXISTS fact_sales",
    "DROP TABLE IF EXISTS fact_aftersales",
    "DROP TABLE IF EXISTS dim_dealer",
    "DROP TABLE IF EXISTS dim_model",
    "DROP TABLE IF EXISTS dim_region",
    "DROP TABLE IF EXISTS doc_reports",
    "CREATE TABLE dim_region(region_id INT PRIMARY KEY, region_name TEXT)",
    "CREATE TABLE dim_model(model_id INT PRIMARY KEY, model_name TEXT, series TEXT)",
    "CREATE TABLE dim_dealer(dealer_id INT PRIMARY KEY, dealer_name TEXT, region_id INT)",
    """CREATE TABLE fact_sales(id INTEGER PRIMARY KEY, date TEXT, model_id INT,
        dealer_id INT, region_id INT, qty INT, amount REAL)""",
    """CREATE TABLE fact_aftersales(id INTEGER PRIMARY KEY, date TEXT, model_id INT,
        dealer_id INT, region_id INT, type TEXT, cost REAL)""",
    "CREATE TABLE doc_reports(id INTEGER PRIMARY KEY, title TEXT, content TEXT)",
]


def run():
    with engine.begin() as conn:
        for stmt in DDL:
            conn.execute(text(stmt))
        for rid, rname in REGIONS:
            conn.execute(text("INSERT INTO dim_region VALUES(:a,:b)"), {"a": rid, "b": rname})
        for mid, mname, series in MODELS:
            conn.execute(text("INSERT INTO dim_model VALUES(:a,:b,:c)"),
                         {"a": mid, "b": mname, "c": series})
        dealers = []
        did = 1
        for rid, rname in REGIONS:
            for k in range(1, 4):  # 每区域 3 家经销商
                dealers.append((did, f"{rname}{k}号店", rid))
                conn.execute(text("INSERT INTO dim_dealer VALUES(:a,:b,:c)"),
                             {"a": did, "b": f"{rname}{k}号店", "c": rid})
                did += 1

        start = date(2026, 1, 1)
        sid = aid = 1
        for d in range(120):  # 约 4 个月
            cur = (start + timedelta(days=d)).isoformat()
            for _ in range(random.randint(8, 16)):
                dealer = random.choice(dealers)
                m = random.choice(MODELS)
                qty = random.randint(1, 5)
                price = {"C级": 35, "E级": 50, "GLC": 45, "GLE": 70, "A级": 25}[m[1]]
                conn.execute(text(
                    "INSERT INTO fact_sales VALUES(:id,:dt,:mid,:did,:rid,:q,:amt)"),
                    {"id": sid, "dt": cur, "mid": m[0], "did": dealer[0],
                     "rid": dealer[2], "q": qty, "amt": qty * price * (0.95 + random.random() * 0.1)})
                sid += 1
            for _ in range(random.randint(2, 6)):
                dealer = random.choice(dealers)
                m = random.choice(MODELS)
                conn.execute(text(
                    "INSERT INTO fact_aftersales VALUES(:id,:dt,:mid,:did,:rid,:tp,:c)"),
                    {"id": aid, "dt": cur, "mid": m[0], "did": dealer[0], "rid": dealer[2],
                     "tp": random.choice(AFTER_TYPES), "c": random.randint(500, 8000)})
                aid += 1

        reports = [
            ("销售额口径说明", "销售额 = 成交数量 × 成交单价，含税；不含金融及保险收入。"),
            ("区域划分说明", "华北含京津冀；华东含江浙沪皖；华南含粤桂闽；西南含川渝云贵；东北含辽吉黑。"),
            ("售后成本口径", "售后成本含工时费与配件成本，召回类不计入门店考核。"),
        ]
        for i, (t1, ct) in enumerate(reports, 1):
            conn.execute(text("INSERT INTO doc_reports VALUES(:i,:t,:c)"),
                         {"i": i, "t": t1, "c": ct})

    print(f"种子数据已写入 {DATABASE_URL}：销售 {sid-1} 行 / 售后 {aid-1} 行")


if __name__ == "__main__":
    run()
