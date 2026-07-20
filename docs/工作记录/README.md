# 工作记录

非「数据获取/处理」的活，都在这里按模块记录（数据获取/处理写进 PRD-1）。

## 怎么用
1. 进自己模块文件夹（后端 / 前端 / 测试 / 运维）。
2. 复制 [`_模板.md`](_模板.md)，改名为 `日期-工单号-简述.md`（如 `2026-05-25-T7-text2sql.md`）。
3. 按模板填写，**详细到新人能看懂**，必要时画 Mermaid 图（见 [团队协作规范](../团队协作规范.md) 第 4 节）。
4. **后端跑通类文档**：写完 .md 后再生成同名 Word（把 mermaid 图渲成图片嵌入，方便直接看图）：
   ```
   NODE_PATH=C:/Users/Lenovo/AppData/Roaming/npm/node_modules node "docs/工作记录/_md_to_word.js" "<md路径>"
   ```
   脚本 `_md_to_word.js` 用 mmdc 渲 mermaid + docx 库拼 Word，支持标题/表格/代码块/列表/加粗/引用。
5. 干完别忘了：更新 `PROJECT-MEMORY/` + 提交 + push（四步见协作规范第 1 节）。

## 模块对应
- `后端/`：Text2SQL、RAG、Agent 编排、图表洞察、API、清洗入库（数据采集本身写 PRD-1）
- `前端/`：对话界面、SSE 渲染、图表/引用卡、知识库上传页
- `测试/`：单测、评测集、RAGAS/DeepEval、CI
- `运维/`：Docker、部署、定时任务、监控、备份
