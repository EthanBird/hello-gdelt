# 04｜GDELT 可计算世界模型：执行路线图与里程碑

版本：v0.1  
日期：2026-07-16  
适用范围：单机 V1，1TB SSD、32GB RAM、8 核 16 线程 CPU

## 1. 计划原则

开发顺序由证据链决定，而不是由界面或模型复杂度决定：

1. 先证明真实数据可以稳定进入本机；
2. 再冻结数据契约和可追溯链路；
3. 再实现最简单、可解释的指标与验证；
4. 最后开放 API、MCP 和自动化调参；
5. 每个阶段必须能独立验收、回滚和复现。

在 P0 验证完成前，不承诺完整工期。下面的周数是单人全职开发的初始预算，用于排序而非发布日期。

## 2. 版本与里程碑

| 里程碑 | 建议版本 | 目标 | 初始预算 | 退出条件 |
|---|---|---|---:|---|
| M0 设计基线 | v0.0.1 | 文档、范围、术语和仓库治理 | 1–2 天 | 三份基线文档入库，Backlog 可执行 |
| M1 开发前验证 | v0.1.0 | 在目标机器跑通真实样本闭环 | 2–4 天 | 生成带证据的 GO/CONDITIONAL GO 报告 |
| M2 数据地基 | v0.2.0 | 配置、控制面、Bronze 接入 | 1 周 | 增量拉取可重入，manifest 与质量检查齐全 |
| M3 语义层 | v0.3.0 | Silver 标准事件与实体/关系映射 | 1–2 周 | 映射版本化，去重稳定，抽样审计通过 |
| M4 状态层 | v0.4.0 | Gold 国家/双边/主题日频表 | 1 周 | 三类核心查询满足正确性与延迟预算 |
| M5 基线模型 | v0.5.0 | 指标、面板回归、walk-forward | 1–2 周 | 指标可解释、可复现，基线与稳健性报告齐全 |
| M6 Hypothesis Lab | v0.6.0 | DSL、编译、实验注册、失败记忆 | 1–2 周 | 能输出 supported/rejected/inconclusive |
| M7 API / MCP | v0.7.0 | 受限查询、证据检索与假设提交 | 1 周 | 无任意 SQL，权限与资源上限测试通过 |
| M8 单机生产化 | v1.0.0 | 调度、备份、恢复、观测与文档 | 1 周 | 连续运行、故障恢复和资源水位验收通过 |

## 3. 阶段执行计划

### M0｜设计基线与治理

交付物：

- README、路线图、Issue Backlog；
- 术语约束：Observed World、narrative pressure、media-observed relation；
- 分支、提交、PR、测试和 ADR 规则；
- V1 明确的非目标清单。

验收：文档之间不存在范围冲突；任何未来开发任务均能关联到一个里程碑和明确验收标准。

### M1｜开发前验证

优先在最终目标机器执行，而不是以 CI 环境结果替代本机结果。

工作包：

1. 硬件、OS、Python 3.11、编译工具与磁盘水位检查；
2. GDELT `lastupdate.txt`、raw、master file list、DOC API 连通性；
3. events / mentions / GKG 样本下载、解压和字段数验证；
4. raw → Bronze Parquet → DuckDB 查询；
5. 最小 Silver / Gold 转换；
6. SQLite WAL/FTS5、FastAPI health、HypothesisSpec schema；
7. 资源与查询基准；
8. 输出诊断报告和 GO 判定。

硬门槛：磁盘空闲低于 300GB、raw 与 BigQuery 均不可用、DuckDB/Parquet 或 SQLite WAL 不可用，判定 NO-GO。

### M2｜数据地基

工作包：

- `pyproject.toml` 与锁定依赖；
- 统一配置加载、路径解析和资源上限；
- SQLite 控制面 schema 与迁移；
- DuckDB session 与只读查询规范；
- GDELT 增量清单、下载、校验、重试和幂等；
- Bronze schema、分区、manifest、lineage；
- 单元测试、契约测试与小样本集成测试。

验收重点：相同输入重复运行不产生重复数据；任务中断可安全恢复；每个 Parquet 分区可追溯到源文件、抓取时间、代码版本和配置版本。

### M3｜Silver 语义层

工作包：

- `silver_world_event` 契约；
- 实体、国家代码、地理与别名映射 v1；
- CAMEO/GKG → 内部关系 taxonomy v1；
- 去重键与 mentions 聚合；
- 映射版本化、未知值隔离和抽样审计；
- 数据质量报告。

验收重点：映射不是静默覆盖；未知/歧义项可查询；映射版本变化能触发确定性重建。

### M4｜Gold 状态层

必须交付：

- `gold_country_day_state`；
- `gold_pair_day_relation`；
- `gold_entity_theme_day`；
- DuckDB 视图和查询基准；
- top evidence 贡献追溯。

性能初始目标应在 M1 基准后冻结。未测量前不写不现实的固定 SLA；首版以“交互式查询秒级、批处理不超内存、扫描分区可解释”为方向。

### M5｜基线指标与验证

第一批指标：

- domestic risk pressure；
- financial stress narrative；
- policy hawkishness；
- policy uncertainty；
- social unrest pressure；
- external conflict pressure；
- bilateral tension；
- media attention shock。

验证要求：

- 指标先做无监督/规则基线，再谈复杂模型；
- 每个指标都有 exposure normalization、季节性处理和参数版本；
- walk-forward 严格按时间切分；
- 保存基线、placebo、敏感性和 FDR 结果；
- 不以单次显著性作为“发现规律”的充分条件。

### M6｜Hypothesis Lab

交付：HypothesisSpec schema、白名单表达式、编译器、runner、实验注册、报告器与失败假设记忆。

安全要求：DSL 只能引用注册特征、允许的变换和受控时间窗；禁止任意 Python、SQL、文件路径或网络调用。

### M7｜API 与 MCP

最小接口：

- 查询国家状态；
- 查询双边关系；
- 查询 top evidence；
- 提交/查询假设实验；
- 查询数据与模型版本。

默认绑定 `127.0.0.1`。所有任务有调用者、时间范围、超时、扫描量、输出行数与并发上限。

### M8｜单机生产化

交付：systemd 服务/定时器、结构化日志、健康检查、磁盘水位保护、备份恢复演练、失败重跑、数据质量日报和运维手册。

## 4. 关键路径

```text
M0 → M1 → M2 → M3 → M4 → M5 → M6 → M7 → M8
```

可并行但不能绕过依赖的工作：

- API 契约草案可与 M3/M4 并行，但真实接口实现依赖 Gold 契约；
- HypothesisSpec schema 可提前设计，但 runner 依赖稳定特征与验证框架；
- Dashboard 可在 M4 后开始，但不属于 V1 核心关键路径；
- BigQuery 历史回填可在 raw 增量稳定后单独推进。

## 5. 风险登记

| 风险 | 早期信号 | 缓解措施 | 决策点 |
|---|---|---|---|
| GDELT schema 漂移 | 字段数/类型检查失败 | raw 保留、schema version、隔离坏分区 | M1/M2 |
| 网络或限流不稳定 | 下载失败率、断点重试增多 | manifest、退避、镜像策略、BigQuery 备选 | M1 |
| 媒体曝光偏差 | 指标与新闻量强相关 | exposure normalization、来源多样性、placebo | M5 |
| 实体映射污染 | unknown/ambiguous 比例升高 | 映射版本化、人工审计样本、禁止静默修复 | M3 |
| 单机资源失控 | spill、OOM、磁盘水位下降 | 分区裁剪、并发上限、临时目录与水位保护 | 全程 |
| 假设挖掘过拟合 | 大量边缘显著结果 | walk-forward、FDR、placebo、失败记忆 | M5/M6 |
| LLM 越权 | 任意查询/参数修改尝试 | 白名单 DSL、只读工具、审计与硬上限 | M6/M7 |

## 6. Definition of Done

一个开发 Issue 只有在以下条件满足后才能关闭：

- 代码、配置或文档已提交；
- 对外契约有类型或 schema；
- 正常、边界和失败路径有测试；
- 资源上限和失败行为已说明；
- 生成数据包含 lineage 和版本；
- 用户可见行为更新了文档；
- PR 中附有复现命令与验收证据；
- 不引入“true risk / actual policy intent”等越界表述。

## 7. 首轮开发决策

建议按以下顺序启动：

1. 完成 Issue 001–004，产出 M1 GO 报告；
2. 仅在 GO 或有明确风险台账的 CONDITIONAL GO 后进入 Issue 005；
3. M2 完成前不开发模型；
4. M4 数据契约稳定前不公开 MCP；
5. M5 基线不能稳定复现时，不进入自动假设发现。

## 8. 进度快照（2026-07-16）

| 项目 | 状态 | 证据 |
|---|---|---|
| M0 文档与仓库治理 | In review | README、AGENTS、CONTRIBUTING、ADR、PR/Issue 模板 |
| 环境预检 | Implemented | Python/依赖/磁盘/SQLite WAL/FTS5 检查与测试 |
| 真实 GDELT probe | Implemented | HTTPS→HTTP 可观测回退、完整批次选择、四重校验 |
| Bronze/Silver/Gold 最小闭环 | Implemented | 真实 Events 批次产生三层 Parquet 与 SQLite lineage |
| 自动化质量检查 | Implemented | Ruff 与 7 个 pytest 测试通过 |
| 目标机器最终 GO 报告 | Pending | 必须在 1TB/32GB/Ryzen 目标机执行默认 500GB 门槛 |

本开发环境的成功只证明代码路径可运行，不代替目标机器上的 PLAN-006 决策。
