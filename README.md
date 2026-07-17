# GDELT Computable World

基于 GDELT 媒体观测数据构建的单机、可调参、可验证、可被大模型受限调用的动态世界模型实验室。

> 本项目描述的是 **Observed World（媒体观测世界）**，不是对真实世界的完整复原。所有风险、关系和政策指标均表示媒体观测与叙事压力，不应被命名或解释为“客观真相”。

## 当前状态

当前为 `v0.1 / 开发前验证与全球市场研究协议阶段`：

- 已完成数学建模定义、单机工程架构和开发前验证方案；
- 已冻结 103 个资产的多市场研究池和 96 个确认性假设单元；
- 已登记主要数据源、许可和再分发边界；
- 已实现本地 M1 preflight、GDELT `lastupdate.txt` 契约、三表字段数验证、受限下载和安全解压；
- 已加入冻结注册表漂移测试和 GitHub Actions CI；
- 真实 GDELT ZIP → Bronze Parquet → DuckDB → Gold 的目标机器闭环仍须通过，尚未宣称任何金融假设得到支持。

研究开发位于 `research/global-news-market-v0.1` 分支。在 M1 获得 `GO` 或明确接受的 `CONDITIONAL GO` 前，不进入正式模型裁决。

## V1 目标

在 1TB SSD、32GB 内存、8 核 16 线程 CPU 的单机上，实现：

- GDELT 受控切片的可复现拉取；
- Bronze / Silver / Gold 三层 Parquet 数据；
- 国家日频状态、双边关系、实体—主题压力查询；
- 风险压力、政策倾向等可解释基线指标；
- Hypothesis DSL、walk-forward、placebo、FDR 与失败假设记忆；
- FastAPI 查询层与受限 MCP 工具层；
- 从指标到原始证据、配置、代码和实验结果的可追溯链路。

V1 的基础世界模型建议范围为 50–80 个国家、8–12 类关系、8 个核心主题。全球新闻—市场研究另设 103 个对象的冻结资产池，以日频为主、合法分钟数据子集为辅，不做全量 GDELT 本地镜像。

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

## 快速验证

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e '.[data,research,dev]'
hello-gdelt preflight --root .
pytest
```

`preflight` 只检查本机依赖、磁盘、SQLite 和运行目录。真实数据门禁还必须完成 GDELT 三表同时间戳下载、字节与 MD5、ZIP CRC、字段数、Parquet 和 DuckDB 查询验证。

## 文档

- [数学建模定义](docs/01_math_modeling_definition.md)
- [单机工程开发文档](docs/02_engineering_development_document.md)
- [开发前验证清单](docs/03_pre_development_validation.md)
- [执行路线图与里程碑](docs/04_development_plan.md)
- [GitHub Issue Backlog](docs/05_github_issue_backlog.md)
- [全球新闻—多市场冻结版研究协议](docs/06_global_news_market_research_protocol.md)
- [M1 开发前验证运行手册](docs/07_m1_validation_runbook.md)

原始设计文档是工程事实基线；冻结版研究协议和 `config/` 注册表是确认性研究事实基线。后续实现若与其不一致，必须通过 ADR 或显式版本变更记录原因。

## 冻结研究注册表

```text
config/asset_universe.yaml       103 个资产或代理
config/hypothesis_registry.yaml  12 个假设族 × 8 个市场组 = 96 个确认性单元
config/data_source_registry.yaml 数据来源与用途
config/licence_matrix.yaml       研究、许可和再分发门禁
```

伦敦贵金属和商品在未取得官方基准许可时只允许使用明确标注的 `PROXY`；交易所或供应商原始市场数据默认不提交到公开仓库。

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

`v0.1.0-validation`：交付开发前验证命令、真实样本、诊断报告和 GO/NO-GO 结论。通过后再进入 `v0.2.0-data-foundation`。

## 许可证

仓库当前公开，但暂未选择开源许可证。在明确数据使用边界、第三方依赖和发布策略前，默认保留全部权利；若决定开放贡献，再补充许可证和贡献约定。
