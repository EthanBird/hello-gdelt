# 02｜GDELT 可计算世界模型：单机工程开发文档

版本：v0.1  
日期：2026-06-23  
目标硬件：1TB 磁盘、32GB 内存、AMD Ryzen 7 8745H，8 核 16 线程  
开发目标：在单台机器上构建可运行、可维护、可回放、可调参、可被大模型调用的 GDELT 世界模型实验室。

---

## 0. 总体结论

这台机器不适合做全量 GDELT 仓库，但完全适合做：

```text
Local Computable World Lab
=
GDELT 受控切片
+ 本地 Parquet 数据湖
+ DuckDB / Polars 本地计算
+ SQLite 控制面
+ 假设验证引擎
+ FastAPI / MCP 工具接口
+ LLM 受限调用
```

核心架构：

```text
GDELT BigQuery / raw files / DOC API
        ↓
受控抽取器 Python
        ↓
Parquet bronze / silver / gold
        ↓
DuckDB + Polars 本地计算
        ↓
SQLite 控制面：参数 / 假设 / 实验 / 任务 / lineage
        ↓
本地模型层：指数模型 / 面板回归 / 离散事件传播 / 轻量状态空间
        ↓
FastAPI：世界状态查询 / 关系查询 / 证据查询 / 假设验证
        ↓
MCP：给大模型调用，但只暴露安全工具
        ↓
LLM：提出数学假设 → 系统验证 → 记录结果 → 修正假设
```

---

## 1. 非目标与边界

### 1.1 第一版不做

```text
不本地镜像全量 GDELT GKG
不本地镜像全量 EventMentions 历史
不抓取并长期保存所有新闻全文
不把所有 person / organization 都做实体化
不存 dense N×N×R×T 全矩阵
不部署 Kafka / Flink / Spark / Kubernetes
不引入 Airflow / Dagster 作为第一版必需组件
不让 LLM 直接执行 SQL
不让 LLM 修改生产参数
不把 GDELT 指标命名为 true risk 或 actual policy intent
```

### 1.2 第一版必须做

```text
本地可复现数据切片
标准化事件表
国家级日频关系表
国家级主题压力表
可配置特征工程
假设 DSL
自动回测
稳健性检验
实验注册
失败假设记忆
API 查询
LLM 工具边界
```

---

## 2. 推荐技术栈

| 层 | 推荐技术 | 是否必需 | 说明 |
|---|---|---:|---|
| 本地列式存储 | Parquet + ZSTD | 是 | 省磁盘、跨工具、适合分区 |
| 本地 SQL 引擎 | DuckDB | 是 | 嵌入式 OLAP，直接查询 Parquet |
| DataFrame / ETL | Polars | 是 | lazy scan、列裁剪、低内存 |
| 控制面数据库 | SQLite WAL | 是 | 单文件、可备份、无需服务 |
| 全文搜索 | SQLite FTS5 | 建议 | 搜索证据标题、摘要、主题 |
| 向量检索 | LanceDB | 可选 | 本地嵌入式向量库 |
| API | FastAPI | 是 | 类型清晰，自动 OpenAPI |
| LLM 工具层 | MCP server 或 FastAPI tools | 建议 | 标准化工具调用 |
| 调度 | APScheduler / systemd timer | 是 | 轻量本地任务调度 |
| 实验记录 | SQLite 自研表；可选 MLflow | 是 | 先自研，后补 MLflow |
| 调参 | Optuna + SQLite | 建议 | 单机超参搜索 |
| Dashboard | Streamlit / Panel / 简单前端 | 可选 | 研究员交互 |
| 测试 | pytest | 是 | 单元、集成、数据质量测试 |

### 2.1 为什么 DuckDB + Parquet

DuckDB 可以直接查询 Parquet，不需要把数据导入数据库；Parquet 的列式格式能支持列裁剪和过滤下推。对于 32GB 内存的单机，这意味着：

```text
查询只读需要列
按日期分区减少扫描
中间结果可落盘
本地开发极简
易备份和迁移
```

### 2.2 为什么 SQLite 做控制面

控制面存的是小而关键的数据：

```text
参数版本
实体映射版本
任务状态
假设定义
实验结果
模型版本
lineage
```

这些数据不需要 OLAP，但需要事务、可备份和易维护。SQLite WAL 足够。

### 2.3 什么可以自研

应该自研：

```text
GDELT → world_event 的标准化规则
实体映射体系
CAMEO/GKG → 内部关系分类
边权重函数
风险指数
政策倾向指数
Hypothesis DSL
假设编译器
验证框架
稳健性检验
失败假设记忆
LLM 权限系统
指标解释和证据追溯
```

不应自研：

```text
列式存储
SQL 引擎
全文搜索底层
HTTP API 框架
向量索引底层
超参数优化框架
```

---

## 3. 进程架构

### 3.1 最小进程

```text
world-api      FastAPI，提供查询和任务提交
world-worker   ETL、模型、回测、索引更新
world-mcp      MCP 工具服务，可与 world-api 合并
```

V1 可以先合并成一个进程：

```text
python -m app.api.main
```

内部启动 APScheduler。

### 3.2 建议 systemd 服务

```ini
[Unit]
Description=GDELT World API
After=network.target

[Service]
WorkingDirectory=/opt/gdelt-world
ExecStart=/opt/gdelt-world/.venv/bin/uvicorn app.api.main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

worker：

```ini
[Unit]
Description=GDELT World Worker
After=network.target

[Service]
WorkingDirectory=/opt/gdelt-world
ExecStart=/opt/gdelt-world/.venv/bin/python -m app.worker.main
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

---

## 4. 仓库结构

```text
gdelt-world/
  app/
    api/
      __init__.py
      main.py
      deps.py
      routes_state.py
      routes_relation.py
      routes_hypothesis.py
      routes_evidence.py
      routes_admin.py
    mcp/
      __init__.py
      server.py
      tools.py
    worker/
      __init__.py
      main.py
      scheduler.py
      job_runner.py

  world_core/
    __init__.py
    config/
      loader.py
      schemas.py
    gdelt_extract/
      bigquery_extract.py
      raw_file_extract.py
      doc_api.py
      lastupdate.py
    storage/
      paths.py
      parquet_io.py
      duckdb.py
      sqlite.py
    entity_resolution/
      resolver.py
      alias_index.py
      validators.py
    relation_taxonomy/
      mapper.py
      cameo.py
      themes.py
    feature_engineering/
      weights.py
      normalize.py
      rolling.py
      country_features.py
      pair_features.py
      theme_features.py
    models/
      base.py
      panel.py
      event_propagation.py
      state_space.py
      metrics.py
    backtest/
      dataset_builder.py
      walk_forward.py
      placebo.py
      fdr.py
      scorer.py
    hypothesis/
      schema.py
      compiler.py
      validator.py
      runner.py
      reporter.py
    evidence/
      index.py
      fts.py
      vector.py
    utils/
      logging.py
      hashing.py
      time.py
      disk.py

  pipelines/
    ingest_recent_gdelt.py
    backfill_bigquery.py
    build_silver_events.py
    build_gold_country_state.py
    build_gold_pair_relation.py
    update_evidence_index.py
    run_daily_model_scores.py
    run_hypothesis_job.py

  configs/
    app.yaml
    resources.yaml
    entities/
      countries.yaml
      central_banks.yaml
      aliases.yaml
    relations/
      cameo_to_relation.yaml
      risk_themes.yaml
      monetary_policy_themes.yaml
    features/
      country_risk_pressure.yaml
      policy_hawkishness.yaml
      bilateral_tension.yaml
    models/
      panel_fx_model.yaml
      conflict_transition_model.yaml
    validation/
      walk_forward.yaml

  sql/
    duckdb/
      create_views.sql
      feature_queries.sql
      backtest_queries.sql
      diagnostics.sql
    sqlite/
      control_schema.sql
      fts_schema.sql
      indexes.sql

  data/
    bronze/
    silver/
    gold/
    evidence/
    vector/
    models/
    reports/
    tmp/
    control/

  notebooks/
    research/
    diagnostics/

  tests/
    unit/
    integration/
    data_quality/

  scripts/
    init_db.py
    check_env.py
    download_sample_gdelt.py
    validate_sample_schema.py
    clean_tmp.py
    backup_control_db.py

  pyproject.toml
  README.md
```

---

## 5. 本地数据目录规范

```text
data/
  bronze/
    gdelt_events/date=YYYY-MM-DD/*.parquet
    gdelt_eventmentions/date=YYYY-MM-DD/*.parquet
    gdelt_gkg/date=YYYY-MM-DD/*.parquet
    manifests/date=YYYY-MM-DD/*.json

  silver/
    world_event/date=YYYY-MM-DD/*.parquet
    world_article/date=YYYY-MM-DD/*.parquet
    entity_mention/date=YYYY-MM-DD/*.parquet

  gold/
    country_day_state/date=YYYY-MM-DD/*.parquet
    pair_day_relation/date=YYYY-MM-DD/*.parquet
    entity_theme_day/date=YYYY-MM-DD/*.parquet
    feature_vector/date=YYYY-MM-DD/*.parquet

  evidence/
    evidence_article.sqlite
    evidence_article_fts.sqlite
    raw_snippets/date=YYYY-MM-DD/*.jsonl

  vector/
    lancedb/

  control/
    world_control.sqlite
    world_control.sqlite-wal
    world_control.sqlite-shm

  models/
    fitted/
    mlruns/

  reports/
    hypothesis/
    daily/
    diagnostics/

  tmp/
    duckdb/
    downloads/
    staging/
```

### 5.1 分区原则

```text
Bronze：按 GDELT 日期分区
Silver：按 event_date 分区
Gold：按 date 分区
Evidence：SQLite 存索引，JSONL/Parquet 存批量元数据
Tmp：允许随时清理
```

### 5.2 磁盘预算

1TB 磁盘建议保留 180GB 以上空闲。

| 用途 | 建议上限 |
|---|---:|
| OS、Python 环境、缓存 | 80–120GB |
| Bronze 原始切片 | 100–150GB |
| Silver 标准事件 | 200–300GB |
| Gold 特征/状态 | 100–180GB |
| Evidence 元数据/FTS/向量 | 80–150GB |
| 模型、实验、报告 | 50–100GB |
| 临时文件和安全空闲 | 180–250GB |

---

## 6. 依赖安装

### 6.1 Python 版本

推荐：

```text
Python 3.11 或 3.12
```

### 6.2 pyproject.toml 示例

```toml
[project]
name = "gdelt-world"
version = "0.1.0"
requires-python = ">=3.11,<3.13"
dependencies = [
  "duckdb>=1.0.0",
  "polars>=1.0.0",
  "pyarrow>=15.0.0",
  "pandas>=2.2.0",
  "numpy>=1.26.0",
  "scipy>=1.12.0",
  "statsmodels>=0.14.0",
  "scikit-learn>=1.4.0",
  "fastapi>=0.110.0",
  "uvicorn[standard]>=0.29.0",
  "pydantic>=2.7.0",
  "pydantic-settings>=2.2.0",
  "httpx>=0.27.0",
  "requests>=2.31.0",
  "python-dotenv>=1.0.0",
  "pyyaml>=6.0.0",
  "orjson>=3.10.0",
  "apscheduler>=3.10.0",
  "typer>=0.12.0",
  "rich>=13.0.0",
  "optuna>=3.6.0",
  "mlflow>=2.12.0",
  "pytest>=8.0.0",
  "pytest-cov>=5.0.0"
]

[project.optional-dependencies]
bigquery = [
  "google-cloud-bigquery>=3.20.0",
  "google-cloud-bigquery-storage>=2.24.0"
]
vector = [
  "lancedb>=0.10.0",
  "sentence-transformers>=3.0.0"
]
mcp = [
  "mcp>=1.0.0"
]
```

### 6.3 初始化命令

```bash
python -m venv .venv
source .venv/bin/activate
pip install -U pip wheel setuptools
pip install -e ".[bigquery,vector,mcp]"
```

---

## 7. 资源配置

`configs/resources.yaml`：

```yaml
resources:
  duckdb:
    memory_limit: "20GB"
    threads: 12
    temp_directory: "data/tmp/duckdb"

  worker:
    max_parallel_etl_jobs: 2
    max_parallel_backtests: 1
    job_timeout_seconds: 3600
    min_free_disk_gb: 180

  api:
    host: "127.0.0.1"
    port: 8000
    max_query_days: 3650
    max_rows_returned: 10000
    request_timeout_seconds: 120

  storage:
    parquet_compression: zstd
    bronze_retention_days: 90
    tmp_retention_days: 7

  gdelt:
    default_ingest_frequency: daily
    raw_lastupdate_url: "http://data.gdeltproject.org/gdeltv2/lastupdate.txt"
    raw_masterfilelist_url: "http://data.gdeltproject.org/gdeltv2/masterfilelist.txt"

  hypothesis:
    max_hypothesis_runtime_seconds: 3600
    max_hypothesis_date_range_days: 3650
    max_hypothesis_entities: 100
    max_placebo_runs: 20
```

---

## 8. SQLite 控制面设计

### 8.1 初始化 PRAGMA

```sql
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA busy_timeout=5000;
PRAGMA temp_store=MEMORY;
PRAGMA foreign_keys=ON;
```

### 8.2 核心表

```sql
CREATE TABLE IF NOT EXISTS data_snapshot (
  data_snapshot_id TEXT PRIMARY KEY,
  source_name TEXT NOT NULL,
  source_range_start TEXT NOT NULL,
  source_range_end TEXT NOT NULL,
  created_at TEXT NOT NULL,
  manifest_json TEXT NOT NULL,
  row_count INTEGER,
  checksum TEXT,
  notes TEXT
);

CREATE TABLE IF NOT EXISTS param_set (
  param_set_id TEXT PRIMARY KEY,
  param_type TEXT NOT NULL,
  version TEXT NOT NULL,
  spec_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  created_by TEXT,
  active INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS entity_registry (
  entity_id TEXT PRIMARY KEY,
  entity_type TEXT NOT NULL,
  canonical_name TEXT NOT NULL,
  country_code TEXT,
  valid_from TEXT,
  valid_to TEXT,
  confidence REAL DEFAULT 1.0,
  source TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS entity_alias (
  alias_text TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  language TEXT,
  confidence REAL DEFAULT 1.0,
  valid_from TEXT,
  valid_to TEXT,
  source TEXT,
  PRIMARY KEY (alias_text, entity_id),
  FOREIGN KEY (entity_id) REFERENCES entity_registry(entity_id)
);

CREATE TABLE IF NOT EXISTS ingest_batch (
  ingest_batch_id TEXT PRIMARY KEY,
  source TEXT NOT NULL,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  status TEXT NOT NULL,
  source_range_start TEXT,
  source_range_end TEXT,
  row_count INTEGER,
  output_path TEXT,
  error_message TEXT
);

CREATE TABLE IF NOT EXISTS job_queue (
  job_id TEXT PRIMARY KEY,
  job_type TEXT NOT NULL,
  spec_json TEXT NOT NULL,
  status TEXT NOT NULL,
  priority INTEGER NOT NULL DEFAULT 100,
  created_at TEXT NOT NULL,
  started_at TEXT,
  finished_at TEXT,
  error_message TEXT,
  artifact_path TEXT
);

CREATE TABLE IF NOT EXISTS hypothesis (
  hypothesis_id TEXT PRIMARY KEY,
  parent_hypothesis_id TEXT,
  claim_text TEXT NOT NULL,
  spec_json TEXT NOT NULL,
  created_by TEXT,
  created_at TEXT NOT NULL,
  status TEXT NOT NULL,
  decision TEXT,
  failure_reason TEXT,
  promoted_to_factor INTEGER DEFAULT 0,
  notes TEXT
);

CREATE TABLE IF NOT EXISTS experiment_run (
  run_id TEXT PRIMARY KEY,
  hypothesis_id TEXT NOT NULL,
  data_snapshot_id TEXT NOT NULL,
  feature_version TEXT NOT NULL,
  param_version TEXT NOT NULL,
  model_version TEXT NOT NULL,
  code_git_sha TEXT,
  started_at TEXT,
  finished_at TEXT,
  status TEXT NOT NULL,
  metrics_json TEXT,
  artifact_path TEXT,
  report_path TEXT,
  FOREIGN KEY (hypothesis_id) REFERENCES hypothesis(hypothesis_id)
);

CREATE TABLE IF NOT EXISTS validation_metric (
  run_id TEXT NOT NULL,
  metric_name TEXT NOT NULL,
  metric_value REAL,
  sample_name TEXT,
  window_start TEXT,
  window_end TEXT,
  p_value REAL,
  q_value REAL,
  ci_low REAL,
  ci_high REAL,
  PRIMARY KEY (run_id, metric_name, sample_name, window_start, window_end)
);

CREATE TABLE IF NOT EXISTS robustness_check (
  run_id TEXT NOT NULL,
  check_type TEXT NOT NULL,
  check_spec_json TEXT NOT NULL,
  passed INTEGER,
  metrics_json TEXT,
  notes TEXT,
  PRIMARY KEY (run_id, check_type, check_spec_json)
);
```

### 8.3 索引

```sql
CREATE INDEX IF NOT EXISTS idx_hypothesis_status ON hypothesis(status);
CREATE INDEX IF NOT EXISTS idx_experiment_hypothesis ON experiment_run(hypothesis_id);
CREATE INDEX IF NOT EXISTS idx_job_status_priority ON job_queue(status, priority, created_at);
CREATE INDEX IF NOT EXISTS idx_entity_alias_entity ON entity_alias(entity_id);
```

---

## 9. DuckDB 使用规范

### 9.1 初始化

```python
import duckdb

con = duckdb.connect("data/control/world.duckdb")
con.execute("PRAGMA threads=12")
con.execute("PRAGMA memory_limit='20GB'")
con.execute("PRAGMA temp_directory='data/tmp/duckdb'")
```

### 9.2 视图

```sql
CREATE OR REPLACE VIEW silver_world_event AS
SELECT *
FROM read_parquet('data/silver/world_event/date=*/part-*.parquet', union_by_name=true);

CREATE OR REPLACE VIEW gold_country_day_state AS
SELECT *
FROM read_parquet('data/gold/country_day_state/date=*/part-*.parquet', union_by_name=true);

CREATE OR REPLACE VIEW gold_pair_day_relation AS
SELECT *
FROM read_parquet('data/gold/pair_day_relation/date=*/part-*.parquet', union_by_name=true);
```

### 9.3 查询规则

必须：

```text
WHERE 中必须有日期过滤
SELECT 只选需要列
结果超过 max_rows_returned 时分页或落盘
长查询必须走 worker，不走 API 同步请求
```

禁止：

```text
SELECT * 扫全历史
API 请求里做三表大 join
LLM 直接提交 SQL
Dense graph 全量展开
```

---

## 10. 数据接入设计

### 10.1 接入模式

| 模式 | 用途 | 第一版优先级 |
|---|---|---:|
| BigQuery 历史回填 | 2018 至今训练集、长期回测 | 高 |
| GDELT raw 15 分钟文件 | 近实时更新、每日状态 | 高 |
| DOC API | 快速探索、关键词趋势 | 中 |
| GDELT Cloud | 可选新接口 | 暂不依赖 |

### 10.2 BigQuery 回填原则

```text
必须使用日期过滤
优先使用 partitioned tables
只选所需列
先 dry-run 估算扫描量
每次抽取写入 data_snapshot
LLM 不得直接发起 BigQuery 查询
```

示例 SQL：

```sql
SELECT
  GlobalEventID,
  SQLDATE,
  MonthYear,
  Year,
  FractionDate,
  Actor1Code,
  Actor1Name,
  Actor1CountryCode,
  Actor2Code,
  Actor2Name,
  Actor2CountryCode,
  EventCode,
  EventBaseCode,
  EventRootCode,
  QuadClass,
  GoldsteinScale,
  NumMentions,
  NumSources,
  NumArticles,
  AvgTone,
  ActionGeo_CountryCode,
  ActionGeo_Lat,
  ActionGeo_Long,
  DATEADDED,
  SOURCEURL
FROM `gdelt-bq.gdeltv2.events_partitioned`
WHERE _PARTITIONTIME BETWEEN TIMESTAMP('2024-01-01') AND TIMESTAMP('2024-01-31')
  AND (
    Actor1CountryCode IN ('US','CH','JA','TU','RS','UP')
    OR Actor2CountryCode IN ('US','CH','JA','TU','RS','UP')
    OR ActionGeo_CountryCode IN ('US','CH','JA','TU','RS','UP')
  )
```

注意：GDELT Actor country code 与 ActionGeo country code 的编码体系不同，必须在实体映射层明确处理。

### 10.3 Raw 文件增量

GDELT 2.0 raw 文件常用入口：

```text
http://data.gdeltproject.org/gdeltv2/lastupdate.txt
http://data.gdeltproject.org/gdeltv2/masterfilelist.txt
```

raw 文件通常包括：

```text
*.export.CSV.zip
*.mentions.CSV.zip
*.gkg.csv.zip
```

处理流程：

```text
读取 lastupdate.txt
解析最新 export / mentions / gkg 文件 URL
下载到 data/tmp/downloads
校验 zip 能打开
读取 TSV/CSV
转换为 bronze parquet
记录 ingest_batch
删除 tmp zip 或保留短期缓存
```

---

## 11. Bronze 层

### 11.1 目标

Bronze 层只负责：

```text
原始切片保存
行数记录
来源记录
schema 记录
checksum
最少变换
```

不要在 Bronze 层做复杂清洗。

### 11.2 bronze_gdelt_events 字段

保留 GDELT 原始字段，并增加：

```text
source_file_url
source_file_type
ingest_batch_id
ingest_time
raw_line_hash
```

### 11.3 manifest

每次写入生成 JSON：

```json
{
  "ingest_batch_id": "ing_20260623_010000",
  "source": "gdelt_raw_lastupdate",
  "files": [
    {
      "url": "http://data.gdeltproject.org/gdeltv2/...export.CSV.zip",
      "local_path": "data/bronze/gdelt_events/date=2026-06-23/part-000.parquet",
      "row_count": 12345,
      "sha256": "..."
    }
  ],
  "created_at": "2026-06-23T01:00:00+09:00"
}
```

---

## 12. Silver 层

### 12.1 silver_world_event

```text
silver_world_event
------------------
event_id
source_event_id
event_time
event_date
actor1_raw
actor2_raw
actor1_entity_id
actor2_entity_id
actor1_country
actor2_country
relation_id
cameo_code
cameo_base_code
cameo_root_code
quad_class
goldstein
avg_tone
num_mentions
num_sources
num_articles
source_url
action_geo_country
action_geo_lat
action_geo_lon
themes
persons
organizations
document_urls
confidence_score
dedupe_key
source_dataset
param_version
ingest_batch_id
created_at
```

### 12.2 生成规则

```text
1. 读取 bronze_gdelt_events
2. 解析事件时间
3. Actor 字段映射到 entity_id
4. CAMEO / QuadClass 映射到 relation_id
5. 标准化 tone / goldstein / mentions
6. 生成 dedupe_key
7. 输出 Parquet
```

### 12.3 dedupe_key

建议：

```text
dedupe_key = hash(
  event_date,
  actor1_entity_id,
  actor2_entity_id,
  cameo_code,
  action_geo_country,
  source_url_normalized
)
```

---

## 13. Gold 层

### 13.1 gold_country_day_state

```text
date
entity_id
state_name
window_days
raw_count
weighted_score
exposure_adjusted_score
zscore
uncertainty
feature_version
param_version
created_at
```

### 13.2 gold_pair_day_relation

```text
date
src_entity_id
dst_entity_id
relation_id
window_days
event_count
mention_count
source_count
source_diversity
avg_tone
goldstein_sum
weighted_score
exposure_adjusted_score
zscore
uncertainty
feature_version
param_version
created_at
```

### 13.3 gold_entity_theme_day

```text
date
entity_id
theme_id
window_days
article_count
source_count
avg_tone
theme_salience
zscore
feature_version
param_version
created_at
```

### 13.4 稀疏存储原则

只存：

```text
有事件的边
超过阈值的边
top-K 边
异常边
研究 universe 中需要的边
```

不要存所有国家对所有国家的所有关系。

---

## 14. 特征配置

### 14.1 country_financial_stress.yaml

```yaml
feature_id: country_financial_stress
entity_level: country
time_bucket: 1d

inputs:
  relations:
    - financial_stress
    - debt_stress
    - banking_stress
  themes:
    - CURRENCY
    - DEBT
    - BANKING
    - IMF
    - INFLATION

windows: [7, 14, 30]

weighting:
  mentions_power: 0.5
  sources_power: 0.7
  tone_weight: 0.4
  goldstein_weight: 0.2
  source_diversity_weight: 0.5

normalization:
  exposure_adjusted: true
  seasonal_zscore: true
  zscore_lookback_days: 365
  zscore_min_periods: 90
  min_sources: 2
  min_mentions: 3

output:
  table: gold_country_day_state
```

### 14.2 policy_hawkishness.yaml

```yaml
feature_id: policy_hawkishness
entity_level: country
time_bucket: 1d

inputs:
  themes:
    hawkish:
      - RATE_HIKE
      - MONETARY_TIGHTENING
      - INFLATION_PRESSURE
      - HIGHER_FOR_LONGER
      - CURRENCY_DEFENSE
    dovish:
      - RATE_CUT
      - MONETARY_EASING
      - RECESSION_RISK
      - GROWTH_SLOWDOWN
      - LIQUIDITY_SUPPORT

windows: [7, 14, 30]

formula:
  type: linear_combination
  expression: hawkish - dovish + inflation_concern - growth_concern + currency_defense

normalization:
  exposure_adjusted: true
  seasonal_zscore: true

output:
  table: gold_country_day_state
```

---

## 15. 模型层设计

### 15.1 Model interface

```python
from abc import ABC, abstractmethod
from typing import Any

class WorldModel(ABC):
    model_id: str

    @abstractmethod
    def fit(self, features: Any, targets: Any, params: dict) -> dict:
        ...

    @abstractmethod
    def score(self, features: Any, params: dict) -> Any:
        ...

    @abstractmethod
    def forecast(self, state: Any, horizon: int, params: dict) -> Any:
        ...

    @abstractmethod
    def explain(self, entity_id: str, date: str) -> dict:
        ...
```

### 15.2 第一版模型

```text
IndexModel：可解释加权指数
PanelRegressionModel：面板回归
EventPropagationModel：离散事件传播
RollingZScoreModel：异常检测
KalmanStateModel：轻量状态空间，可后续加入
```

### 15.3 模型运行策略

```text
日内：更新聚合特征和简单状态
每日：更新主要指标和模型评分
每周：跑关键假设回测
每月：重估参数、重算 seasonal zscore、清理数据
```

---

## 16. Hypothesis Lab 设计

### 16.1 HypothesisSpec Pydantic

```python
from pydantic import BaseModel, Field
from typing import Literal, list

class UniverseSpec(BaseModel):
    entity_type: Literal["country", "pair", "organization", "market"]
    group: str | None = None
    entities: list[str] | None = None
    start_date: str
    end_date: str

class FeatureSpec(BaseModel):
    feature_id: str
    window_days: int
    transform: str = "exposure_adjusted_zscore"
    lag_days: int = 1

class TargetSpec(BaseModel):
    target_id: str
    horizon_days: int

class ModelSpec(BaseModel):
    type: Literal["panel_regression", "logit", "poisson", "negbin", "event_propagation"]
    fixed_effects: list[str] = []
    controls: list[str] = []

class ValidationSpec(BaseModel):
    method: Literal["walk_forward"]
    train_start: str
    test_start: str
    metrics: list[str]

class HypothesisSpec(BaseModel):
    hypothesis_id: str | None = None
    claim: str
    universe: UniverseSpec
    feature: FeatureSpec
    target: TargetSpec
    model: ModelSpec
    expected_effect: dict
    validation: ValidationSpec
    robustness: dict = Field(default_factory=dict)
```

### 16.2 假设状态机

```text
draft
  ↓ compile
compiled
  ↓ enqueue
queued
  ↓ run
running
  ↓ score
supported / rejected / inconclusive
  ↓ promote
promoted_to_candidate_factor
```

### 16.3 假设运行流程

```text
1. LLM 或用户提交 HypothesisSpec
2. schema 校验
3. 权限校验
4. 成本估计
5. 写入 hypothesis 表
6. 创建 job_queue
7. worker 构建数据集
8. 运行模型
9. 运行 walk-forward
10. 运行 placebo
11. 计算 q-value
12. 写 experiment_run / validation_metric / robustness_check
13. 生成 Markdown 报告
14. 返回结果摘要
```

---

## 17. API 设计

### 17.1 状态查询

```http
GET /v1/entities/{entity_id}/state?start_date=2024-01-01&end_date=2024-12-31&state_name=financial_stress
```

返回：

```json
{
  "entity_id": "COUNTRY_TUR",
  "state_name": "financial_stress",
  "series": [
    {"date": "2024-01-01", "zscore": 1.2, "value": 0.034}
  ],
  "meta": {
    "feature_version": "v1",
    "param_version": "risk_v1"
  }
}
```

### 17.2 关系查询

```http
GET /v1/relations?src=COUNTRY_USA&dst=COUNTRY_CHN&relation=verbal_conflict&start_date=2024-01-01&end_date=2024-12-31
```

### 17.3 证据查询

```http
GET /v1/evidence/search?q=Turkey%20currency%20crisis&start_date=2024-01-01&end_date=2024-12-31
```

### 17.4 假设提交

```http
POST /v1/hypotheses/compile
POST /v1/hypotheses/run
GET  /v1/hypotheses/{hypothesis_id}
GET  /v1/runs/{run_id}
```

### 17.5 管理接口

```http
GET /v1/admin/health
GET /v1/admin/disk
GET /v1/admin/jobs
POST /v1/admin/jobs/{job_id}/cancel
```

---

## 18. MCP 工具层

### 18.1 暴露工具

```text
get_world_state
get_relation_timeseries
search_evidence
compile_hypothesis
estimate_hypothesis_cost
run_hypothesis_backtest
get_hypothesis_result
compare_hypotheses
propose_revision
```

### 18.2 权限边界

LLM 可以：

```text
查状态
查关系
查证据
提交 HypothesisSpec
触发受限回测
读取实验结果
提出修正
```

LLM 不可以：

```text
执行任意 SQL
删除数据
修改实体映射
修改生产参数
发布模型
绕过 FDR
绕过 placebo
把 inconclusive 改成 supported
```

### 18.3 资源限制

```yaml
llm_tool_limits:
  max_date_range_days: 3650
  max_entities: 100
  max_rows_returned: 10000
  max_runtime_seconds: 3600
  max_memory_gb: 20
  max_concurrent_jobs: 1
  require_dry_run_for_backtest: true
```

---

## 19. Evidence 系统

### 19.1 evidence_article 表

```sql
CREATE TABLE IF NOT EXISTS evidence_article (
  evidence_id TEXT PRIMARY KEY,
  event_id TEXT,
  date TEXT NOT NULL,
  url TEXT,
  title TEXT,
  source_domain TEXT,
  source_country TEXT,
  language TEXT,
  themes TEXT,
  persons TEXT,
  organizations TEXT,
  locations TEXT,
  tone REAL,
  snippet TEXT,
  content_hash TEXT,
  embedding_id TEXT,
  created_at TEXT NOT NULL
);
```

### 19.2 FTS5

```sql
CREATE VIRTUAL TABLE IF NOT EXISTS evidence_article_fts
USING fts5(
  title,
  snippet,
  themes,
  persons,
  organizations,
  content='evidence_article',
  content_rowid='rowid'
);
```

### 19.3 证据贡献度

每个指标应能追溯 top contributors：

```text
entity_id
state_name
date
evidence_id
contribution_weight
reason
```

---

## 20. 调度

### 20.1 日频任务

```text
01:00 ingest_recent_gdelt
01:20 build_silver_world_event
01:40 build_gold_country_day_state
02:00 build_gold_pair_day_relation
02:20 update_evidence_index
02:40 run_daily_model_scores
03:00 refresh_dashboard_cache
```

### 20.2 周频任务

```text
重新估计模型参数
跑关键假设滚动回测
更新假设排行榜
生成周报
清理 bronze 旧数据
备份 SQLite 和 configs
```

### 20.3 月频任务

```text
长期特征回填
重估 seasonal zscore
检查实体映射质量
跑完整 robustness suite
生成质量报告
```

---

## 21. 数据质量检查

### 21.1 Bronze 检查

```text
zip 能打开
行数 > 0
字段数符合预期
日期在合理范围
重复文件未重复写入
checksum 记录存在
```

### 21.2 Silver 检查

```text
event_id 唯一
actor/entity 映射率达到阈值
relation_id 非空率达到阈值
event_date 与 DATEADDED 合理
tone 范围合理
goldstein 范围合理
lat/lon 范围合理
```

### 21.3 Gold 检查

```text
每个日期有数据
zscore 非全空
极端值经过 winsorize
window 聚合不使用未来数据
feature_version / param_version 非空
```

### 21.4 假设检查

```text
不能使用未来数据
训练测试时间不能重叠
horizon 必须为正
feature lag 必须 >= 0
control variables 必须存在
placebo 必须记录
```

---

## 22. 备份与恢复

### 22.1 每日备份

```bash
mkdir -p backups/$(date +%F)
sqlite3 data/control/world_control.sqlite ".backup backups/$(date +%F)/world_control.sqlite"
cp -r configs backups/$(date +%F)/configs
cp -r data/reports backups/$(date +%F)/reports
```

### 22.2 每周备份

```text
备份 SQLite
备份 configs
备份 hypothesis reports
备份 model artifacts
备份 Gold 层最近 90 天
```

### 22.3 不必长期备份

```text
Bronze tmp zip
DuckDB tmp
旧 raw downloads
可从 BigQuery 或 GDELT raw 重建的切片
```

---

## 23. 性能优化顺序

按优先级：

```text
1. 少取数据：只取国家、主题、关系、日期切片
2. 预聚合：Silver → Gold
3. 分区：date partition
4. 列裁剪：不要 SELECT *
5. 稀疏存储：不落 dense graph
6. 缓存：常用状态和 dashboard
7. 限流：LLM 工具必须限时限量
8. 清理：tmp 和旧 bronze 定期删
```

### 23.1 DuckDB 查询规范

```sql
-- 好
SELECT date, entity_id, zscore
FROM read_parquet('data/gold/country_day_state/date=*/part-*.parquet')
WHERE date BETWEEN DATE '2024-01-01' AND DATE '2024-12-31'
  AND entity_id = 'COUNTRY_TUR'
  AND state_name = 'financial_stress';

-- 坏
SELECT *
FROM read_parquet('data/silver/world_event/date=*/part-*.parquet');
```

---

## 24. 安全设计

### 24.1 本地绑定

默认只监听：

```text
127.0.0.1
```

如果需要局域网访问，必须加认证。

### 24.2 禁止任意 SQL

API 不提供：

```text
/run_sql
/query_raw
```

只提供参数化查询。

### 24.3 文件路径安全

所有路径必须限定在项目目录：

```text
Path.resolve().is_relative_to(PROJECT_ROOT)
```

禁止：

```text
../
绝对路径写入
用户指定输出任意文件
```

### 24.4 LLM 工具安全

```text
所有工具只接受 JSON schema
所有 backtest 进入队列
所有任务有超时
所有任务有最大日期范围
所有任务记录调用者和 spec
```

---

## 25. 开发路线图

### 第 1 周：骨架

```text
仓库初始化
配置系统
SQLite 控制面
DuckDB 连接
数据目录
环境检查脚本
```

### 第 2 周：真实数据接入

```text
lastupdate 拉取
下载一个 export/mentions/gkg 样本
转 bronze parquet
BigQuery dry-run
小范围历史回填
```

### 第 3 周：Silver

```text
GDELT 字段解析
实体映射 v1
关系 taxonomy v1
silver_world_event
数据质量检查
```

### 第 4 周：Gold

```text
country_day_state
pair_day_relation
entity_theme_day
DuckDB 查询视图
简单 dashboard
```

### 第 5 周：模型

```text
风险指数
政策倾向指数
面板回归
walk-forward
placebo
```

### 第 6 周：Hypothesis Lab

```text
Hypothesis DSL
compiler
runner
experiment registry
Markdown 报告
```

### 第 7 周：API / MCP

```text
FastAPI 查询
证据搜索
MCP 工具
权限限制
```

### 第 8 周：生产化

```text
systemd
日志
备份
质量报告
失败恢复
文档补全
```

---

## 26. 完成标准

第一版可用的定义：

```text
能从 GDELT 拉到真实数据
能生成 bronze/silver/gold
能查询某国风险状态
能查询某双边关系时间序列
能追溯 top evidence
能提交 HypothesisSpec
能自动跑 walk-forward
能输出 supported/rejected/inconclusive
能记录失败假设
能被 LLM 通过受限工具调用
能在 1TB/32GB 单机上稳定运行
```

---

## 27. 参考资料

- GDELT Data： https://www.gdeltproject.org/data.html
- GDELT 2.0 发布说明： https://blog.gdeltproject.org/gdelt-2-0-our-global-world-in-realtime/
- GDELT Events / EventMentions / GKG 联合查询： https://blog.gdeltproject.org/complex-queries-combining-events-eventmentions-and-gkg/
- GDELT partitioned BigQuery tables： https://blog.gdeltproject.org/announcing-partitioned-gdelt-bigquery-tables/
- DuckDB Parquet： https://duckdb.org/docs/current/data/parquet/overview.html
- Polars： https://docs.pola.rs/
- SQLite WAL： https://sqlite.org/wal.html
- SQLite FTS5： https://sqlite.org/fts5.html
- FastAPI： https://fastapi.tiangolo.com/
- MCP： https://modelcontextprotocol.io/docs/getting-started/intro
- Optuna： https://optuna.readthedocs.io/
- MLflow Tracking： https://mlflow.org/docs/latest/ml/tracking/
- LanceDB Quickstart： https://docs.lancedb.com/quickstart
