# GDELT Computable World

基于 GDELT 媒体观测数据构建的单机、可调参、可验证、可被大模型受限调用的动态世界模型实验室。

> 本项目描述的是 **Observed World（媒体观测世界）**，不是对真实世界的完整复原。所有风险、关系和政策指标均表示媒体观测与叙事压力，不应被命名或解释为“客观真相”。

## 当前状态

当前为 `v0.1 / 设计基线阶段`：

- 已完成数学建模定义；
- 已完成单机工程架构设计；
- 已完成开发前验证方案；
- 尚未宣称任何数据接入、指标或模型已经实现；
- 正式开发必须先通过开发前 `GO / CONDITIONAL GO / NO-GO` 门禁。

## V1 目标

在 1TB SSD、32GB 内存、8 核 16 线程 CPU 的单机上，实现：

- GDELT 受控切片的可复现拉取；
- Bronze / Silver / Gold 三层 Parquet 数据；
- 国家日频状态、双边关系、实体—主题压力查询；
- 风险压力、政策倾向等可解释基线指标；
- Hypothesis DSL、walk-forward、placebo、FDR 与失败假设记忆；
- FastAPI 查询层与受限 MCP 工具层；
- 从指标到原始证据、配置、代码和实验结果的可追溯链路。

V1 的建议范围为 50–80 个国家、8–12 类关系、8 个核心主题，先做日频指数、面板回归和离散事件传播，不做全量 GDELT 本地镜像。

## 核心架构

```text
GDELT raw / DOC API / BigQuery controlled backfill
                    ↓
              Python ingest
                    ↓
       Parquet Bronze / Silver / Gold
                    ↓
          DuckDB + Polars compute
                    ↓
 SQLite control plane + experiment registry
                    ↓
 Baseline models + Hypothesis validation engine
                    ↓
        FastAPI + restricted MCP tools
```

关键选型：

| 层 | V1 选型 |
|---|---|
| 列式存储 | Parquet + ZSTD |
| 本地 OLAP | DuckDB |
| ETL / DataFrame | Polars |
| 控制面 | SQLite WAL + FTS5 |
| API | FastAPI |
| 调度 | APScheduler / systemd timer |
| 测试 | pytest + 数据契约检查 |
| 调参 | Optuna（按需引入） |

## 文档

- [数学建模定义](docs/01_math_modeling_definition.md)
- [单机工程开发文档](docs/02_engineering_development_document.md)
- [开发前验证清单](docs/03_pre_development_validation.md)
- [执行路线图与里程碑](docs/04_development_plan.md)
- [GitHub Issue Backlog](docs/05_github_issue_backlog.md)

三份原始设计文档是当前事实基线；后续实现若与设计不一致，必须通过 ADR 或文档变更明确记录原因。

## 开发门禁

首个开发里程碑不是“开始写模型”，而是跑通真实样本闭环：

```text
GDELT sample
  → raw validation
  → Bronze Parquet
  → Silver world_event
  → Gold aggregate
  → DuckDB query
  → SQLite experiment record
  → FastAPI health
```

必须满足的 GO 条件包括：核心依赖可安装、GDELT raw 可访问、至少一个事件文件可下载解压、Parquet 可写、DuckDB 可查、SQLite WAL/FTS5 可用、端到端样本能生成 Gold 表。BigQuery、LanceDB 或 DOC API 暂不可用可判定为 `CONDITIONAL GO`，但必须记录风险。

## 工作方式

- `main` 只保留通过检查的可运行状态；
- 每个 Issue 对应一个小范围分支与一个 PR；
- 任何数据表都必须有 schema、主键/去重键、分区策略和质量检查；
- 任何指标都必须有定义、参数版本、证据追溯和适用边界；
- 任何假设验证都必须明确训练窗、测试窗、基线、指标和多重检验方法；
- LLM 不得执行任意 SQL、修改生产参数或绕过资源限制。

## 建议的首个版本

`v0.1.0-validation`：只交付开发前验证命令、真实样本、诊断报告和 GO/NO-GO 结论。通过后再进入 `v0.2.0-data-foundation`。

## 许可证

暂未选择开源许可证。在明确数据使用边界、第三方依赖和发布策略前，建议保持私有仓库。
