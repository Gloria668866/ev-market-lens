# RAG 检索、证据覆盖与拒答回归报告

> 执行真实 hybrid recall → rerank → evidence gate → parent merge，并确定性核对种子原文、merged context 与人工关键锚点。不代表生成答案的 faithfulness/correctness。

- 样本：**20**（正例 13，负例 7）
- 严格正例通过率：**100.0%**（13/13）
- 标注 claim 原文有效率：**100.0%**
- merged context claim 覆盖率：**100.0%**
- 关键锚点覆盖率：**100.0%**
- 负例拒答率：**100.0%**
- reranker 全程启用：**True**
- 后端披露：`local SQLite + NumPy evaluation backend; this is not the production PostgreSQL/pgvector backend`
- Git：`53b4fa367aca0b086c0e7976284469ec19e810ba`，dirty=False
- 种子 manifest：`35b29e2b740ad5924a96f6bc57bf4037fdbaec21fd0729f17580039e31cfa6bb`

## 正例

| id | 类别 | Top-K 召回 | 上下文召回 | claim 覆盖 | 锚点覆盖 | 严格通过 |
|---|---|---:|---:|---:|---:|---:|
| rag-001 | single | 100.0% | 100.0% | 100.0% | 100.0% | True |
| rag-002 | single | 100.0% | 100.0% | 100.0% | 100.0% | True |
| rag-003 | single | 100.0% | 100.0% | 100.0% | 100.0% | True |
| rag-004 | single | 100.0% | 100.0% | 100.0% | 100.0% | True |
| rag-005 | single | 100.0% | 100.0% | 100.0% | 100.0% | True |
| rag-006 | single | 100.0% | 100.0% | 100.0% | 100.0% | True |
| rag-007 | single | 100.0% | 100.0% | 100.0% | 100.0% | True |
| rag-008 | single | 100.0% | 100.0% | 100.0% | 100.0% | True |
| rag-009 | single | 100.0% | 100.0% | 100.0% | 100.0% | True |
| rag-010 | single | 100.0% | 100.0% | 100.0% | 100.0% | True |
| rag-011 | cross | 100.0% | 100.0% | 100.0% | 100.0% | True |
| rag-012 | cross | 100.0% | 100.0% | 100.0% | 100.0% | True |
| rag-013 | cross | 100.0% | 100.0% | 100.0% | 100.0% | True |

## 负例

| id | 是否拒答 | 原因 |
|---|---:|---|
| rag-014 | True | missing_query_anchor |
| rag-015 | True | missing_query_anchor |
| rag-016 | True | low_score |
| rag-017 | True | low_score |
| rag-018 | True | missing_query_anchor |
| rag-019 | True | low_score |
| rag-020 | True | low_score |

## 口径边界

- 本报告不调用最终答案生成模型。
- `claim_source_valid_rate` 只检查人工 evidence/anchors 是否确实存在于其标注的原始种子文件。
- `retrieved_claim_support_rate` 与 `critical_anchor_support_rate` 按来源检查最终 merged context；无关文档中的相同文字不能代替目标来源。
- 仍需单独建设生成答案 faithfulness、correctness 与 citation precision 评测。
