# 06｜Hypothesis Lab V1

Hypothesis Lab 是项目的科学验证控制面。大模型或研究员只提交结构化 `HypothesisSpec`，不能提交任意 SQL、Python、文件路径或网络调用。

## 当前能力

- 严格 Pydantic DSL，拒绝未知字段；
- 注册式特征与目标目录；
- 不可变、可哈希的实验计划；
- 实体/日期过滤、lag 与 horizon 对齐；
- OLS 与 panel OLS 基线；
- expanding-window walk-forward；
- 日期打乱、实体打乱、特征打乱和反转时间安慰剂；
- Benjamini-Hochberg FDR 批量校正；
- `supported / rejected / inconclusive` 三态裁决；
- SQLite WAL 实验注册表；
- Markdown 报告和数据 lineage；
- 资源预算与运行时门禁。

## CLI

```bash
python -m pip install -e '.[dev]'
hello-gdelt hypothesis validate examples/hypotheses/financial_stress_fx.json
hello-gdelt hypothesis compile examples/hypotheses/financial_stress_fx.json
hello-gdelt hypothesis demo --registry data/control/hypothesis.sqlite --report reports/demo.md
```

`demo` 使用确定性合成数据验证端到端流程，不代表任何真实世界发现。

## 裁决原则

`SUPPORTED` 必须同时满足：预期方向、q 值、效应阈值、滚动窗口方向稳定性、样本外指标和安慰剂超越门槛。显著但方向相反时判定 `REJECTED`；其余情况判定 `INCONCLUSIVE`。

LLM 只能解释系统裁决，不能自行把结果改成 supported。

## 下一步

1. 接入 DuckDB/Parquet `DatasetProvider`；
2. 加入时间聚类或实体聚类稳健标准误；
3. 实现 alternative-window 自动敏感性运行；
4. 增加面板固定效应的更高效去均值实现；
5. 将实验任务接入本地 worker 和 FastAPI/MCP；
6. 用真实 GDELT Gold 特征和市场数据执行首批预注册假设。
