#!/usr/bin/env bash
# 车市镜 · 下载本地 Embedding/Reranker 权重到 MODELS_DIR（默认 ./models），挂进容器 /models。
# 用一次性 Python 容器从 ModelScope 下（国内快、不连 HuggingFace）。约 2.8GB，跑一次即可。
# 用法（仓库根）：  bash deploy/download_models.sh
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; [ -f .env.prod ] && . ./.env.prod; set +a
MODELS_DIR=${MODELS_DIR:-./models}
mkdir -p "$MODELS_DIR"

echo ">> 下载 BGE-large-zh-v1.5 + bge-reranker-base 到 $MODELS_DIR （ModelScope）…"
docker run --rm -v "$(pwd)/$MODELS_DIR:/models" python:3.12-slim sh -c "
  pip install --no-cache-dir -i ${PIP_INDEX_URL:-https://pypi.org/simple} modelscope >/dev/null
  python - <<'PY'
from modelscope import snapshot_download
snapshot_download('AI-ModelScope/bge-large-zh-v1.5', local_dir='/models/bge-large-zh-v1.5')
snapshot_download('BAAI/bge-reranker-base',          local_dir='/models/bge-reranker-base')
print('done')
PY
"
echo "✅ 模型就绪：$MODELS_DIR/bge-large-zh-v1.5 + bge-reranker-base"
