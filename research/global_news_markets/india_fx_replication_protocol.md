# GDELT—USD/INR 外部样本复验协议

版本：v1.0-pre-results  
定位：Stage 1 的独立真实数据复验，不替代主研究的原始 GDELT 抽取。

## 数据

公开数据集 `AmritJain/gdelt-india-research-datasets`，由发布者说明包含 GDELT 事件、印度每日 Goldstein 指标和 USD/INR 日频汇率。程序运行时通过 Hugging Face Hub API 枚举文件，优先选择同时含日期、汇率与 GDELT 指标的合并文件；若不存在，则按日期合并 `india_daily_goldstein_averages.csv` 与 `usd_inr_exchange_rates_1year.csv`。

第三方清洗数据存在口径和字段质量风险，因此所有字段映射、文件 SHA-256、缺失率、日期范围和重复率必须输出。此复验的结果只能标记为 `EXTERNAL_REPLICATION`。

## 预注册假设

- INR-H1：较高 Goldstein 稳定性分数对次日 USD/INR 收益具有非零解释力；
- INR-H2：更负的媒体 Tone 对次日 USD/INR 收益具有非零解释力；
- INR-H3：更高事件/提及强度对次日 USD/INR 绝对收益具有正向解释力。

不预注册方向的 H1/H2 使用双侧检验；H3 要求正向。

## 模型与门禁

- 目标：下一交易日对数收益、下一交易日绝对收益；
- 控制：当日收益、当日绝对收益；
- 推断：OLS + HAC(5)；
- 多重检验：BH-FDR，q ≤ 0.10；
- 安慰剂：100 次时间循环移位，经验 p ≤ 0.10；
- 样本外：扩展窗、20 日测试块，RMSE 改善 > 0；
- 稳定性：滚动折方向一致率 ≥ 0.60；
- 最少有效观测：120。

全部门禁通过才记为 `SUPPORTED_EXTERNAL_REPLICATION`，否则为 `INCONCLUSIVE` 或 `DATA_INSUFFICIENT`。
