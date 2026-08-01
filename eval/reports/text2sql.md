# Text2SQL 执行准确率评测报告

- 样本数：**60**，最大重试：2
- **执行准确率(EX，带自校验重试)：98.3%**（59/60）
- 首次执行准确率(不重试)：98.3%（59/60）
- **自校验重试增益：+0.0 个百分点**

## 错误/失败案例

| id | att | 问题 | 预测SQL/报错 |
|---|---|---|---|
| sql-055 | 1 | 理想L6 2025年每月销量 | SELECT d.ym, s.series_name, SUM(f.volume) AS monthly_volume FROM fact_sales_rank f JOIN dim_series s ON s.series_id = f. |