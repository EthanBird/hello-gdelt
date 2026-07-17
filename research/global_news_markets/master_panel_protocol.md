# GDELT 新闻状态与五类宏观资产：2019—2026 外部面板预注册协议

版本：v1.0-pre-results  
冻结日期：2026-07-17  
定位：真实 GDELT 衍生数据的多资产外部验证；不替代最终原始 GDELT + 官方市场数据确认。

## 数据

第三方公开数据集 `AmritJain/gdelt-india-research-datasets` 中的 `master_dataset/Super_Master_Dataset.csv`。开发前数据审计显示其日期范围为 2019-01-02 至 2026-01-15，共 1,825 行，无字段级缺失，包含：

- 市场水平：`INR`、`OIL`、`GOLD`、`US10Y`、`DXY`；
- 印度新闻：`IN_Avg_Tone`、`IN_Avg_Stability`、`IN_Total_Mentions`、`IN_Panic_Index`；
- 美国新闻：`US_Avg_Tone`、`US_Avg_Stability`、`US_Total_Mentions`、`US_Panic_Index`；
- 跨国差异：`Diff_Stability`、`Diff_Tone`。

文件 SHA-256 必须在运行时重新计算并记录。因为市场序列与 GDELT 特征由第三方整理，本研究只能称为 `EXTERNAL_MULTI_ASSET_VALIDATION`。

## 资产变换

对 `INR`、`OIL`、`GOLD`、`DXY` 使用对数收益。`US10Y` 使用水平一阶差分，避免对收益率水平取对数造成含义混乱。

对每个资产构造：

- 1日未来变化；
- 5日未来累计变化；
- 1日未来绝对变化；
- 5日未来绝对累计变化。

## 新闻特征

十个预注册特征均基于 60 个交易日滚动历史标准化，最少 30 日：

1. `IN_Avg_Tone`；
2. `IN_Avg_Stability`；
3. `log1p(IN_Total_Mentions)`；
4. `IN_Panic_Index`；
5. `US_Avg_Tone`；
6. `US_Avg_Stability`；
7. `log1p(US_Total_Mentions)`；
8. `US_Panic_Index`；
9. `Diff_Stability`；
10. `Diff_Tone`。

## 假设族

### MP-RET

每个新闻特征对每个资产未来 1日与5日变化具有非零增量解释力。该族采用双侧检验，不预注册方向。

### MP-VOL

每个新闻特征对每个资产未来 1日与5日绝对变化具有正向增量解释力。

总计：10 特征 × 5 资产 × 2 horizon × 2 目标族 = 200 个预注册检验。

## 模型

基线包含：

- 被解释资产自身当日变化与绝对变化；
- 其余四个资产当日变化；
- 星期效应；
- 常数项。

增量模型在基线上加入一个预注册新闻特征。全样本推断使用 OLS + Newey-West/HAC，1日 horizon 使用 5 阶，5日 horizon 使用 10 阶。

## 时间验证

1. 扩展窗 walk-forward：初始训练截至 2021-12-31，随后按约 63 个交易日测试块滚动；
2. 最终保留样本：2025-01-01 至 2026-01-15，仅用于单独的 holdout RMSE 比较；
3. 训练参数不得使用 holdout 之后的信息。

## 多重检验与安慰剂

- 按 `MP-RET-horizon` 与 `MP-VOL-horizon` 四个族分别执行 BH-FDR；
- 主门槛 q ≤ 0.05；
- 200 次循环移位安慰剂，经验 p ≤ 0.05；
- OOS RMSE 改善 > 0；
- 滚动折系数方向一致率 ≥ 0.60；
- 至少 750 个有效观测。

全部通过才记为 `SUPPORTED_EXTERNAL_MULTI_ASSET`。其余为 `INCONCLUSIVE` 或 `DATA_INSUFFICIENT`。

## 稳健性输出

不改变主裁决的附加分析：

- 2019—2021、2022—2024、2025—2026 三时期系数；
- 极端新闻冲击（|z|≥2）事件均值；
- 资产与新闻特征相关矩阵；
- 结果对 horizon、市场和新闻来源的分层统计。

任何探索性分组结果不得升级为预注册支持结论。
