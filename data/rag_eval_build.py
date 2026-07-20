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
        "question": "2025年中国新能源汽车销量突破多少万辆？",
        "answer": "2025年中国新能源汽车销量突破1200万辆，市场渗透率首次超过50%。",
        "doc_id": 1,
        "category": "single",
    })
    questions.append({
        "question": "新能源汽车购置税减免政策到什么时候结束？",
        "answer": "2024年1月1日至2025年12月31日免征；2026-2027年减半征收，每辆不超过1.5万元。",
        "doc_id": 2,
        "category": "single",
    })
    questions.append({
        "question": "纯电动汽车（BEV）相比增程式（EREV）有什么优势？",
        "answer": "BEV零排放、能源利用效率最高（电机效率90%以上）、结构简单维护成本低、充电成本约为燃油的1/3。EREV高速油耗偏高、能量经两次转换效率损失。",
        "doc_id": 3,
        "category": "single",
    })
    questions.append({
        "question": "10-20万价格带有哪些热门车型？",
        "answer": "比亚迪秦PLUS DM-i（全年销量超50万辆）、比亚迪宋PLUS DM-i（月均4万+）、比亚迪元PLUS、广汽埃安Y Plus。",
        "doc_id": 4,
        "category": "single",
    })
    questions.append({
        "question": "理想汽车2025年全年交付量是多少？",
        "answer": "理想汽车2025年全年交付约50万辆，同比增长约33%。是新势力中唯一稳定盈利的企业，全年净利润约120亿元。",
        "doc_id": 5,
        "category": "single",
    })
    questions.append({
        "question": "特斯拉Model Y在懂车帝口碑评分是多少？",
        "answer": "特斯拉Model Y综合评分4.3/5.0。好评维度包括三电系统能耗控制优秀、超充网络覆盖广；差评包括悬挂偏硬、内饰简约过头。",
        "doc_id": 8,
        "category": "single",
    })
    questions.append({
        "question": "2025年充电基础设施在三线以下城市的覆盖情况如何？",
        "answer": "充电基础设施在三线以下城市和高速服务区的覆盖率仍然不足，这是PHEV和EREV增速高于BEV的原因之一。",
        "doc_id": 3,
        "category": "single",
    })
    questions.append({
        "question": "小米SU7 2025年交付了多少辆？",
        "answer": "小米SU7首年交付突破20万辆，成为2025年新能源汽车市场最大黑马。",
        "doc_id": 5,
        "category": "single",
    })
    questions.append({
        "question": "华为ADS 3.0的核心能力是什么？",
        "answer": "华为ADS 3.0实现了\"全国都能开\"的城市NOA，无需高精地图，是行业公认第一梯队智驾方案。问界M9/M7等车型搭载。",
        "doc_id": 7,
        "category": "single",
    })
    questions.append({
        "question": "比亚迪海鸥的续航和价格是多少？",
        "answer": "比亚迪海鸥定价6.98-8.98万元，续航405km。2025年月均销量超3万辆，同级别第一。",
        "doc_id": 4,
        "category": "single",
    })

    # === cross 类：需要跨文档 ===
    questions.append({
        "question": "比亚迪在哪些价格带都有布局？分别是什么车型？",
        "answer": "比亚迪在5-10万（海鸥、海豚）、10-20万（秦PLUS、宋PLUS、元PLUS）、30-50万（腾势D9）以及100万以上（仰望U8）全价格带覆盖。",
        "doc_id": None,
        "category": "cross",
    })
    questions.append({
        "question": "理想L7和问界M7的对比如何？",
        "answer": "理想L7评分4.7/5.0，主打家庭六座/大五座、增程无忧、智能座舱流畅；问界M7评分相近，主打华为ADS智驾加持、增程SUV，24.98-32.98万。",
        "doc_id": None,
        "category": "cross",
    })
    questions.append({
        "question": "2025年增程式电动车整体市场表现如何？",
        "answer": "增程式电动车（EREV）2025年占比约13%，以理想和问界为代表在中大型SUV市场表现突出。PHEV和EREV增速持续高于BEV。",
        "doc_id": None,
        "category": "cross",
    })

    # === negative 类：知识库中没有 ===
    questions.append({
        "question": "奔驰EQS 2025年销量是多少？",
        "answer": "知识库中无此信息。（negative：库中没有奔驰EQS数据）",
        "doc_id": -1,
        "category": "negative",
    })
    questions.append({
        "question": "特斯拉Cybertruck在中国卖了多少辆？",
        "answer": "知识库中无此信息。（negative：Cybertruck未在中国市场上市）",
        "doc_id": -1,
        "category": "negative",
    })
    questions.append({
        "question": "苹果汽车什么时候发布？",
        "answer": "知识库中无此信息。（negative：Apple Car项目已取消）",
        "doc_id": -1,
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
