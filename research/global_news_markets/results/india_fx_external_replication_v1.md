# GDELT—USD/INR 外部样本复验 v1

状态：已完成真实数据执行  
执行日期：2026-07-17  
数据窗口：2025-01-02 至 2025-12-24  
有效面板：252 日；回归有效样本：238 日

## 数据与字段

程序从 `AmritJain/gdelt-india-research-datasets` 枚举并下载六个候选 CSV，最终按预注册选择规则使用：

`correlation_analysis/political_news_exchange_merged.csv`

字段映射：

- 日期：`Date`；
- GDELT Goldstein：`GoldsteinScale_mean`；
- GDELT Tone：`AvgTone_mean`；
- 新闻强度：`Total_mentions`；
- USD/INR：`USD_to_INR`。

主文件 SHA-256：`4d7d6e464003123f5250928c1bb04df373c8310c5207ae2712518860b29a09fc`。

## 预注册结果

| 假设 | β | HAC p | BH q | 时间安慰剂 p | OOS RMSE 改善 | 六折方向一致率 | 裁决 |
|---|---:|---:|---:|---:|---:|---:|---|
| Goldstein z30 → 次日 USD/INR 收益 | 0.0000924 | 0.5982 | 0.6952 | 0.4653 | -0.58% | 100% | INCONCLUSIVE |
| Tone z30 → 次日 USD/INR 收益 | 0.0003193 | 0.1315 | 0.3945 | 0.0495 | -3.43% | 100% | INCONCLUSIVE |
| 提及强度 z30 → 次日绝对收益 | 0.0000449 | 0.6952 | 0.6952 | 0.6436 | -0.07% | 100% | INCONCLUSIVE |

## 实质解释

1. 没有任何假设同时通过 FDR、时间安慰剂、样本外增益和方向稳定门禁。
2. Tone 是最值得注意的反例：时间移位安慰剂经验 p 约为 0.05，且六个扩展窗系数均为正；若只看这两项，很容易声称存在稳定关系。但其 HAC 双侧 p 为 0.132、FDR q 为 0.395，而且加入 Tone 后样本外 RMSE 从 0.002693 上升至 0.002785，恶化约 3.43%。
3. 因而现有证据更支持“媒体 Tone 与 USD/INR 的关系可能随共同状态缓慢变化，但不构成可用的一日预测信号”，而不是支持新闻预测汇率。
4. 本结果为第三方整理数据的外部复验，不能替代原始 GDELT 事件和官方汇率数据上的确认性研究。

## 可复现证据

GitHub Actions 作业 `india-fx-replication` 已完整通过下载、分析、产物上传与强制门禁。研究包包含：

- 六个原始 CSV 及 SHA-256；
- 字段和缺失率审计；
- 252 行分析面板；
- HAC、FDR、安慰剂和滚动样本外结果；
- 两张正式图；
- manifest 和运行日志。

Artifact digest：`sha256:7d715f2db044bdade1bcac7aa3649a876af133c220ffe2834a8d0fae9094a8e4`。
