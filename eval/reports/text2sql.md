# Text2SQL 执行准确率评测报告

- 样本数：**60**，最大重试：2
- **执行准确率(EX，带自校验重试)：78.3%**（47/60）
- 首次执行准确率(不重试)：76.7%（46/60）
- **自校验重试增益：+1.7 个百分点**

## 错误/失败案例

| id | att | 问题 | 预测SQL/报错 |
|---|---|---|---|
| sql-009 | 1 | 2025年5月销量第一的车系 | SELECT s.series_name FROM fact_sales_rank f JOIN dim_series s ON s.series_id = f.series_id JOIN dim_date d ON d.date_id  |
| sql-012 | 1 | 五菱宏光MINIEV累计销量 | SELECT s.series_name, SUM(f.volume) AS total_volume FROM fact_sales_rank f JOIN dim_series s ON s.series_id = f.series_i |
| sql-014 | 1 | 理想汽车全系2025年累计销量 | SELECT s.series_name, SUM(f.volume) AS total_volume FROM fact_sales_rank f JOIN dim_series s ON s.series_id = f.series_i |
| sql-021 | 1 | 2025年各动力类型的总销量 | SELECT s.powertrain, SUM(f.volume) AS total_volume FROM fact_sales_rank f JOIN dim_series s ON s.series_id = f.series_id |
| sql-022 | 1 | 指导价低于15万的纯电车系有多少个 | SELECT COUNT(*) FROM dim_series WHERE guide_price_min < 15 AND powertrain = '纯电' LIMIT 200 |
| sql-024 | 1 | 海鸥2025年累计销量 | SELECT s.series_name, SUM(f.volume) AS total_volume FROM fact_sales_rank f JOIN dim_series s ON s.series_id = f.series_i |
| sql-036 | 1 | AION Y累计销量 | SELECT s.series_name, SUM(f.volume) AS total_volume FROM fact_sales_rank f JOIN dim_series s ON s.series_id = f.series_i |
| sql-038 | 1 | 宋Pro DM累计销量 | SELECT s.series_name, SUM(f.volume) AS total_volume FROM fact_sales_rank f JOIN dim_series s ON s.series_id = f.series_i |
| sql-040 | 1 | 五菱汽车2025年累计销量 | SELECT b.brand_name, SUM(f.volume) AS total_volume FROM fact_sales_rank f JOIN dim_series s ON s.series_id = f.series_id |
| sql-047 | 1 | Model 3累计销量 | SELECT s.series_name, SUM(f.volume) AS total_volume FROM fact_sales_rank f JOIN dim_series s ON s.series_id = f.series_i |
| sql-051 | 1 | 银河E5累计销量 | SELECT s.series_name, SUM(f.volume) AS total_volume FROM fact_sales_rank f JOIN dim_series s ON s.series_id = f.series_i |
| sql-059 | 1 | 2025年纯电销量总和与插混销量总和 | SELECT SUM(CASE WHEN f.new_energy_type = 1 THEN f.volume ELSE 0 END) AS 纯电销量总和, SUM(CASE WHEN f.new_energy_type = 2 THEN |
| sql-060 | 1 | 2025年12月排名上升的车系有哪些（当月排名优于上期） | SELECT s.series_name FROM fact_sales_rank f JOIN dim_series s ON s.series_id = f.series_id JOIN dim_date d ON d.date_id  |