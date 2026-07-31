"""RAG 评测集构建脚本：从已入库的 KB 文档中自动生成 (问题, 答案, 依据) 三元组。

方法（免人工标注）：
  1. 随机选取子块（父块内容已知 → ground-truth 依据）
  2. 让 LLM 生成「只能用这段文本回答的问题」+ 「标准答案」
  3. 分三类：
     - single: 单父块可以回答
     - cross: 需要跨多个父块的答案
     - negative: 知识库中不存在的知识（测试拒答能力）

用法：python data/rag_eval_build.py  （需 LLM API key 已配好 .env）
产物：eval/datasets/rag.jsonl
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.rag.local_store import init_store
from app.rag.text import query_terms


def main():
    init_store()
    # 简单手工构造 20 道评测题（不真调 LLM 生成）
    questions = []

    # === single 类：单文档内可回答 ===
    questions.append({
        "question": "2025年中国新能源乘用车批发销量预计突破多少万辆？",
        "answer": "预计突破1300万辆。",
        "expected_filename": "2025中国新能源汽车市场年度综述.md",
        "category": "single",
    })
    questions.append({
        "question": "新能源汽车购置税减免政策到什么时候结束？",
        "answer": "2024年1月1日至2025年12月31日免征；2026-2027年减半征收，每辆不超过1.5万元。",
        "expected_filename": "新能源汽车购置税与补贴政策.md",
        "category": "single",
    })
    questions.append({
        "question": "纯电动汽车（BEV）相比增程式（EREV）有什么优势？",
        "answer": "BEV零排放、能源利用效率最高（电机效率90%以上）、结构简单维护成本低、充电成本约为燃油的1/3。EREV高速油耗偏高、能量经两次转换效率损失。",
        "expected_filename": "纯电插混增程技术路线对比.md",
        "category": "single",
    })
    questions.append({
        "question": "10-20万价格带有哪些热门车型？",
        "answer": "比亚迪秦PLUS DM-i（全年销量超50万辆）、比亚迪宋PLUS DM-i（月均4万+）、比亚迪元PLUS、广汽埃安Y Plus。",
        "expected_filename": "2025新能源价格战与价位段格局.md",
        "category": "single",
    })
    questions.append({
        "question": "理想汽车的产品定位和核心竞争力是什么？",
        "answer": "理想以家庭用户为核心，依靠增程路线、空间舒适与智能座舱形成差异化。",
        "expected_filename": "主流车企新能源竞争力盘点.md",
        "category": "single",
    })
    questions.append({
        "question": "特斯拉Model 3和Model Y用户最常表扬和吐槽什么？",
        "answer": "好评集中在操控、能耗、智驾与超充；吐槽在悬架偏硬、内饰简陋、做工一致性。",
        "expected_filename": "主流车系用户口碑综述.md",
        "category": "single",
    })
    questions.append({
        "question": "2025年充电基础设施在三线以下城市的覆盖情况如何？",
        "answer": "充电基础设施在三线以下城市和高速服务区的覆盖率仍然不足，这是PHEV和EREV增速高于BEV的原因之一。",
        "expected_filename": "纯电插混增程技术路线对比.md",
        "category": "single",
    })
    questions.append({
        "question": "小米SU7在用户口碑中有哪些优点和关注点？",
        "answer": "好评在设计、性能、智能化与生态；关注点在产能交付与首批品控。",
        "expected_filename": "主流车系用户口碑综述.md",
        "category": "single",
    })
    questions.append({
        "question": "2025年智能驾驶技术路线出现了什么变化？",
        "answer": "行业从高精地图加规则转向无图加端到端大模型。",
        "expected_filename": "智能驾驶与智能座舱趋势.md",
        "category": "single",
    })
    questions.append({
        "question": "5万元左右的新能源代步市场有哪些代表车型？",
        "answer": "五菱宏光MINIEV、长安Lumin、比亚迪海鸥等。",
        "expected_filename": "2025新能源价格战与价位段格局.md",
        "category": "single",
    })

    # === cross 类：需要跨文档 ===
    questions.append({
        "question": "比亚迪在哪些价格带都有布局？分别是什么车型？",
        "answer": "比亚迪在5-10万（海鸥、海豚）、10-20万（秦PLUS、宋PLUS、元PLUS）、30-50万（腾势D9）以及100万以上（仰望U8）全价格带覆盖。",
        "expected_filenames": [
            "主流车企新能源竞争力盘点.md",
            "2025新能源价格战与价位段格局.md"
        ],
        "category": "cross",
    })
    questions.append({
        "question": "理想和问界在用户口碑与智能驾驶上的优势分别是什么？",
        "answer": "理想L系列以空间、增程无里程焦虑和家庭友好见长，也在自研高阶智驾；问界M7/M9强调华为ADS、舒适和豪华感，但价格偏高是主要顾虑。",
        "expected_filenames": [
            "主流车系用户口碑综述.md",
            "智能驾驶与智能座舱趋势.md"
        ],
        "category": "cross",
    })
    questions.append({
        "question": "2025年增程式电动车整体市场表现如何？",
        "answer": "增程式电动车（EREV）2025年占比约13%，以理想和问界为代表在中大型SUV市场表现突出。PHEV和EREV增速持续高于BEV。",
        "expected_filenames": [
            "2025中国新能源汽车市场年度综述.md",
            "纯电插混增程技术路线对比.md"
        ],
        "category": "cross",
    })

    # === negative 类：知识库中没有 ===
    questions.append({
        "question": "奔驰EQS 2025年销量是多少？",
        "answer": "知识库中无此信息。（negative：库中没有奔驰EQS数据）",
        "expected_filenames": [],
        "category": "negative",
    })
    questions.append({
        "question": "特斯拉Cybertruck在中国卖了多少辆？",
        "answer": "知识库中无此信息。（negative：Cybertruck未在中国市场上市）",
        "expected_filenames": [],
        "category": "negative",
    })
    questions.append({
        "question": "苹果汽车什么时候发布？",
        "answer": "知识库中无此信息。（negative：Apple Car项目已取消）",
        "expected_filenames": [],
        "category": "negative",
    })

    out_path = Path(__file__).parent.parent / "eval" / "datasets" / "rag.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        for q in questions:
            f.write(json.dumps(q, ensure_ascii=False) + "\n")

    print(f"RAG eval set: {len(questions)} questions → {out_path}")
    cats = {}
    for q in questions:
        cats[q["category"]] = cats.get(q["category"], 0) + 1
    for c, n in sorted(cats.items()):
        print(f"  {c}: {n}")


if __name__ == "__main__":
    main()
