# 05｜GitHub Issue Backlog

版本：v0.1  
日期：2026-07-16

本文件是仓库初始化时要创建的 Issue 清单。Issue 编号是计划编号，不预设 GitHub 最终编号。

## 标签建议

| 标签 | 用途 |
|---|---|
| `type:foundation` | 工程与仓库基础 |
| `type:data` | 数据接入、转换与质量 |
| `type:model` | 指标、模型与验证 |
| `type:api` | FastAPI / MCP |
| `type:ops` | 调度、备份、观测 |
| `type:docs` | 文档、ADR、契约 |
| `priority:p0` | 阻塞关键路径 |
| `priority:p1` | 当前里程碑必须完成 |
| `priority:p2` | 可延期增强 |
| `status:blocked` | 有明确外部依赖 |

## M0｜设计基线

### PLAN-001｜冻结 V1 范围、术语与非目标

标签：`type:docs`, `priority:p0`  
依赖：无

验收标准：

- 三份设计基线、路线图和 README 可互相引用；
- V1 范围固定为 50–80 国、日频、8–12 类关系和 8 个核心主题；
- 明确 Observed World 术语；
- 明确不做全量镜像、任意 SQL、复杂集群和 LLM 直接改生产参数。

### PLAN-002｜建立开发约定、ADR 与数据契约规则

标签：`type:foundation`, `type:docs`, `priority:p1`  
依赖：PLAN-001

验收标准：定义分支/PR/提交规范、Definition of Done、ADR 模板、schema 版本规则和数据 lineage 最小字段。

## M1｜开发前验证

### PLAN-003｜实现本机环境与资源预检命令

标签：`type:foundation`, `priority:p0`  
依赖：PLAN-001

验收标准：检查 CPU、内存、磁盘、Python、编译工具、核心依赖、临时目录和安全绑定；输出机器可读 JSON 与 Markdown 摘要。

### PLAN-004｜验证 GDELT 网络、raw 样本与 schema

标签：`type:data`, `priority:p0`  
依赖：PLAN-003

验收标准：真实访问 lastupdate/master list/DOC API；下载至少一个 events 样本；校验 zip、字段数和错误路径；记录 URL、时间、大小与哈希。

### PLAN-005｜跑通 raw → Bronze → Silver → Gold 最小闭环

标签：`type:data`, `priority:p0`  
依赖：PLAN-004

验收标准：产生三层小样本 Parquet；DuckDB 可查询；SQLite WAL/FTS5 可用；转换可重复执行且结果稳定。

### PLAN-006｜生成性能基准与 GO/NO-GO 报告

标签：`type:foundation`, `type:docs`, `priority:p0`  
依赖：PLAN-005

验收标准：报告包含硬件、网络、数据格式、读写性能、查询延迟、磁盘水位、失败项和 GO/CONDITIONAL GO/NO-GO 决策。

## M2｜数据地基

### PLAN-007｜初始化 Python 项目、配置系统与质量门禁

标签：`type:foundation`, `priority:p0`  
依赖：PLAN-006（GO 或批准的 CONDITIONAL GO）

验收标准：Python 3.11 项目、锁定依赖、lint/type/test 命令、分环境配置、路径安全和资源上限可用。

### PLAN-008｜实现 SQLite 控制面与迁移

标签：`type:foundation`, `priority:p1`  
依赖：PLAN-007

验收标准：参数、任务、数据集、lineage、假设、实验和模型版本核心表可迁移；WAL、索引、备份和并发测试通过。

### PLAN-009｜实现 GDELT 增量下载器与 manifest

标签：`type:data`, `priority:p0`  
依赖：PLAN-007、PLAN-008

验收标准：支持发现、下载、校验、重试、断点恢复、幂等和失败隔离；禁止未验证文件进入 Bronze。

### PLAN-010｜实现 Bronze writer 与数据质量检查

标签：`type:data`, `priority:p0`  
依赖：PLAN-009

验收标准：schema、分区、ZSTD、manifest、行数/空值/枚举检查齐全；可从源文件追溯到分区。

## M3｜Silver 语义层

### PLAN-011｜定义实体与国家映射 v1

标签：`type:data`, `priority:p0`  
依赖：PLAN-010

验收标准：别名、国家代码、地理层级、未知值和歧义状态有版本化契约；提供抽样审计报告。

### PLAN-012｜定义关系 taxonomy 与 CAMEO/GKG 映射 v1

标签：`type:data`, `type:model`, `priority:p0`  
依赖：PLAN-010

验收标准：8–12 类关系的映射、方向、符号和例外规则可配置、可测试、可版本化。

### PLAN-013｜实现 silver_world_event 与稳定去重

标签：`type:data`, `priority:p0`  
依赖：PLAN-011、PLAN-012

验收标准：数据契约、dedupe key、mentions 聚合、时间标准化、映射版本和坏记录隔离通过测试。

## M4｜Gold 状态层

### PLAN-014｜实现三个 Gold 日频数据集

标签：`type:data`, `priority:p0`  
依赖：PLAN-013

验收标准：country day、pair day、entity-theme day 三表可增量重建；稀疏存储、曝光归一化输入和 lineage 齐全。

### PLAN-015｜建立 DuckDB 查询视图与证据贡献追溯

标签：`type:data`, `type:api`, `priority:p1`  
依赖：PLAN-014

验收标准：三类核心查询与 top evidence 查询正确；扫描分区、延迟和内存有基准。

## M5｜基线模型

### PLAN-016｜实现八个核心指标的可解释基线

标签：`type:model`, `priority:p0`  
依赖：PLAN-014、PLAN-015

验收标准：每个指标有公式、配置、参数版本、单位、边界、归一化、证据贡献和回归测试。

### PLAN-017｜实现 walk-forward、placebo、FDR 与敏感性检验

标签：`type:model`, `priority:p0`  
依赖：PLAN-016

验收标准：严格时间切分；实验可复现；输出效应、置信区间、预测/解释指标、多重检验结果和失败原因。

### PLAN-018｜实现面板回归与离散事件传播基线

标签：`type:model`, `priority:p1`  
依赖：PLAN-017

验收标准：至少有简单基准模型；不存在时间泄漏；模型卡记录数据窗、特征、参数、限制和比较结果。

## M6｜Hypothesis Lab

### PLAN-019｜实现 HypothesisSpec 与白名单编译器

标签：`type:model`, `priority:p0`  
依赖：PLAN-017

验收标准：只允许注册特征、变换和模型；恶意 SQL/Python/路径/网络输入被拒绝；schema 与编译单测齐全。

### PLAN-020｜实现实验 runner、注册表与失败假设记忆

标签：`type:model`, `priority:p0`  
依赖：PLAN-008、PLAN-019

验收标准：自动生成数据窗、运行验证、保存 lineage、输出 Markdown 报告，并稳定判定 supported/rejected/inconclusive。

## M7｜API / MCP

### PLAN-021｜实现只读 FastAPI 查询层

标签：`type:api`, `priority:p0`  
依赖：PLAN-015

验收标准：状态、关系、主题、证据、版本接口有 Pydantic 契约、分页、时间窗、超时和集成测试；默认仅监听本机。

### PLAN-022｜实现受限 MCP 工具与假设提交

标签：`type:api`, `type:model`, `priority:p0`  
依赖：PLAN-020、PLAN-021

验收标准：没有任意 SQL；所有调用可审计；扫描量、输出行数、并发、超时和假设能力均有硬限制。

## M8｜单机生产化

### PLAN-023｜实现调度、日志、磁盘水位与失败恢复

标签：`type:ops`, `priority:p0`  
依赖：PLAN-010、PLAN-021

验收标准：日/周/月任务可调度；结构化日志、失败重试、坏分区隔离、磁盘保护和健康状态可用。

### PLAN-024｜完成备份恢复演练与 v1.0 验收

标签：`type:ops`, `type:docs`, `priority:p0`  
依赖：PLAN-022、PLAN-023

验收标准：SQLite、配置、映射、实验元数据和必要 Gold 数据可恢复；完成连续运行测试；逐项满足工程文档“完成标准”。

## 建议首轮只创建的 Issues

仓库初始化时先创建 PLAN-001 至 PLAN-006。其余任务保留在 Backlog 文档中；M1 得到 GO 结论后再分批创建，避免在真实数据和性能尚未验证前制造虚假的精确计划。
