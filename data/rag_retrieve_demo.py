"""RAG 检索演示脚本（无须启动服务端）。
运行：python data/rag_retrieve_demo.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.rag.retrieve import hybrid_recall
from app.rag.local_store import init_store, stats


def demo():
    init_store()
    d, k = stats()
    print(f"=== RAG 知识库检索演示 ===\n{d} 文档 / {k} chunks\n")

    questions = [
        ("比亚迪", "比亚迪销量和市场地位"),
        ("政策", "购置税减免政策细节"),
        ("技术对比", "BEV vs PHEV vs EREV 区别"),
        ("车型口碑", "特斯拉Model Y 优缺点"),
        ("智能驾驶", "华为ADS和小鹏XNGP"),
        ("新势力", "理想汽车的盈利能力"),
        ("价格", "20-30万买什么新能源车"),
        ("出口", "中国新能源汽车出口到哪里"),
    ]

    for tag, question in questions:
        print(f"── Q: {question} ──")
        results = hybrid_recall(1, question)
        print(f"   召回 {len(results)} 个候选项")
        for i, r in enumerate(results[:3]):
            heading = r.get("heading_path", "")
            content = (r.get("content", "") or "")[:100].replace("\n", " ")
            score = r.get("score", 0)
            print(f"   [{i+1}] score={score:.3f}  {heading}")
            print(f"       \"{content}...\"")
        if len(results) == 0:
            print(f"   ⚠️  无匹配结果——可能需补充语料")
        print()


if __name__ == "__main__":
    demo()
