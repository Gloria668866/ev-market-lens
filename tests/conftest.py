"""pytest 公共配置：把项目根与 data/ 加入 sys.path，离线跑模型。"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.join(ROOT, "data")):
    if p not in sys.path:
        sys.path.insert(0, p)
os.environ.setdefault("HF_HUB_OFFLINE", "1")
