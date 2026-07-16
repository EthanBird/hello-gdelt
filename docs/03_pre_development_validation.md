# 03｜GDELT 可计算世界模型：开发前验证清单与真实数据拉取测试

版本：v0.1  
日期：2026-06-23  
目标：在正式开发前，验证本地环境、磁盘、内存、Python 依赖、网络连通性、GDELT raw 文件、GDELT DOC API、BigQuery dry-run、样本数据格式和本地 Parquet/DuckDB/SQLite 可用性。

---

## 0. 验证目标

本文件用于回答以下问题：

```text
这台机器能不能稳定运行项目？
Python 和依赖是否可安装？
网络能否访问 GDELT？
能否真实拉取 GDELT raw 文件？
raw 文件格式是否符合预期？
能否写入 Parquet？
DuckDB 能否直接查 Parquet？
SQLite WAL/FTS5 是否可用？
BigQuery 是否可 dry-run 和小样本查询？
FastAPI 是否能启动？
Hypothesis DSL 是否能通过 schema 校验？
```

完成本文件所有检查后，再进入正式工程开发。

---

## 1. 验证总清单

| 类别 | 检查项 | 必须通过 |
|---|---|---:|
| 硬件 | CPU、内存、磁盘、空闲空间 | 是 |
| OS | Python、编译环境、curl、unzip | 是 |
| Python | venv、pip、核心包导入 | 是 |
| 网络 | DNS、HTTP/HTTPS、GDELT raw、DOC API | 是 |
| GDELT raw | lastupdate、下载 zip、解压、读取样本 | 是 |
| GDELT 格式 | export / mentions / gkg 字段数检查 | 是 |
| 本地存储 | Parquet 写入、ZSTD 压缩、目录分区 | 是 |
| DuckDB | 直接查询 Parquet、过滤、聚合 | 是 |
| SQLite | WAL、schema、FTS5 | 是 |
| BigQuery | 认证、dry-run、小样本查询 | 建议 |
| API | FastAPI / health endpoint | 是 |
| 资源限制 | 内存、临时目录、磁盘水位 | 是 |
| 安全 | 不暴露 0.0.0.0、不支持任意 SQL | 是 |

---

## 2. 基础系统检查

### 2.1 查看 CPU

Linux：

```bash
lscpu
```

期待：

```text
CPU(s): 16
Thread(s) per core: 2
Core(s) per socket: 8
Model name 包含 AMD Ryzen 7 8745H
```

macOS：

```bash
sysctl -n machdep.cpu.brand_string
sysctl -n hw.ncpu
```

Windows PowerShell：

```powershell
Get-CimInstance Win32_Processor | Select-Object Name,NumberOfCores,NumberOfLogicalProcessors
```

### 2.2 查看内存

Linux：

```bash
free -h
```

期待：

```text
Mem 总量约 32GB
可用内存至少 16GB
```

### 2.3 查看磁盘

Linux/macOS：

```bash
df -h .
```

期待：

```text
可用空间 >= 700GB 更好
最低不要低于 500GB
正式运行时始终保留 >= 180GB 空闲
```

### 2.4 建立项目目录

```bash
mkdir -p ~/gdelt-world
cd ~/gdelt-world
mkdir -p data/{bronze,silver,gold,evidence,vector,models,reports,tmp,control}
mkdir -p data/tmp/{duckdb,downloads,staging}
mkdir -p scripts app/api configs/relations configs/entities configs/features
```

---

## 3. Python 环境检查

### 3.1 Python 版本

```bash
python3 --version
```

要求：

```text
Python 3.11.x 或 3.12.x
```

### 3.2 创建虚拟环境

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip wheel setuptools
```

### 3.3 安装最小依赖

```bash
pip install duckdb polars pyarrow pandas numpy scipy statsmodels scikit-learn \
  fastapi uvicorn pydantic pydantic-settings httpx requests pyyaml orjson \
  apscheduler typer rich optuna pytest
```

可选：

```bash
pip install mlflow google-cloud-bigquery google-cloud-bigquery-storage lancedb
```

### 3.4 依赖导入测试

```bash
python - <<'PY'
import duckdb, polars, pyarrow, pandas, numpy, scipy, statsmodels, sklearn
import fastapi, pydantic, httpx, requests, yaml, orjson, apscheduler, typer, rich
print("core imports ok")
print("duckdb", duckdb.__version__)
print("polars", polars.__version__)
PY
```

通过标准：

```text
无 ImportError
能打印 duckdb / polars 版本
```

---

## 4. 网络连通性检查

### 4.1 DNS 与基础 HTTP

```bash
python - <<'PY'
import socket
for host in ["data.gdeltproject.org", "www.gdeltproject.org", "api.gdeltproject.org"]:
    print(host, socket.gethostbyname(host))
PY
```

通过标准：

```text
三个域名均能解析到 IP。
```

如果无法解析：

```text
检查本地 DNS
检查代理
检查防火墙
检查公司或地区网络限制
```

### 4.2 GDELT raw lastupdate

```bash
curl -L --max-time 30 http://data.gdeltproject.org/gdeltv2/lastupdate.txt | head
```

预期：返回若干行，每行通常包含：

```text
文件大小 URL
```

URL 中可能包含：

```text
.export.CSV.zip
.mentions.CSV.zip
.gkg.csv.zip
```

### 4.3 GDELT masterfilelist

```bash
curl -L --max-time 30 http://data.gdeltproject.org/gdeltv2/masterfilelist.txt | tail -n 5
```

预期：能看到最近文件列表。

### 4.4 DOC API 快速检查

```bash
curl -L --max-time 30 "https://api.gdeltproject.org/api/v2/doc/doc?query=central%20bank&mode=timelinevol&format=json&timespan=1d" | head -c 500
```

预期：返回 JSON，包含 timeline 或类似字段。

如果失败：

```text
检查代理
检查 DNS
检查公司或地区网络限制
改用浏览器访问 URL
必要时配置 HTTPS_PROXY / HTTP_PROXY
```

---

## 5. GDELT raw 文件真实拉取测试

### 5.1 下载最新文件列表并解析

创建脚本 `scripts/download_sample_gdelt.py`：

```python
from __future__ import annotations

import zipfile
from pathlib import Path

import httpx

LASTUPDATE_URL = "http://data.gdeltproject.org/gdeltv2/lastupdate.txt"
DOWNLOAD_DIR = Path("data/tmp/downloads")
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)


def fetch_text(url: str) -> str:
    with httpx.Client(timeout=60, follow_redirects=True) as client:
        r = client.get(url)
        r.raise_for_status()
        return r.text


def parse_lastupdate(text: str) -> dict[str, str]:
    out = {}
    for line in text.strip().splitlines():
        parts = line.strip().split()
        if not parts:
            continue
        url = parts[-1]
        if ".export.CSV.zip" in url:
            out["events"] = url
        elif ".mentions.CSV.zip" in url:
            out["mentions"] = url
        elif ".gkg.csv.zip" in url:
            out["gkg"] = url
    return out


def download(url: str) -> Path:
    path = DOWNLOAD_DIR / url.rsplit("/", 1)[-1]
    with httpx.Client(timeout=120, follow_redirects=True) as client:
        r = client.get(url)
        r.raise_for_status()
        path.write_bytes(r.content)
    return path


def inspect_zip(path: Path, n_lines: int = 3) -> None:
    print(f"\n== {path.name} ==")
    print(f"size_mb={path.stat().st_size / 1024 / 1024:.2f}")
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
        print("zip_names=", names)
        name = names[0]
        with zf.open(name) as f:
            for _ in range(n_lines):
                line = f.readline()
                if not line:
                    break
                print(line[:300])


def main() -> None:
    text = fetch_text(LASTUPDATE_URL)
    urls = parse_lastupdate(text)
    print(urls)
    if not urls:
        raise SystemExit("No GDELT URLs parsed from lastupdate.txt")
    for kind, url in urls.items():
        print("downloading", kind, url)
        path = download(url)
        inspect_zip(path)


if __name__ == "__main__":
    main()
```

运行：

```bash
mkdir -p scripts
python scripts/download_sample_gdelt.py
```

通过标准：

```text
能解析 events / mentions / gkg 中至少一种
能下载 zip
zip 能打开
能打印前几行 bytes
```

### 5.2 下载失败时的最小诊断

```bash
curl -I --max-time 30 http://data.gdeltproject.org/gdeltv2/lastupdate.txt
curl -L --max-time 30 http://data.gdeltproject.org/gdeltv2/lastupdate.txt -o /tmp/lastupdate.txt
file /tmp/lastupdate.txt
head /tmp/lastupdate.txt
```

如果返回 HTML 而不是文本，说明可能被代理或网关拦截。

---

## 6. GDELT raw 字段数验证

### 6.1 事件文件字段数

GDELT 2.0 Events 文件字段很多，开发时不应靠肉眼判断，而要写字段数检查。

创建 `scripts/validate_raw_gdelt_zip.py`：

```python
from __future__ import annotations

import csv
import zipfile
from pathlib import Path

DOWNLOAD_DIR = Path("data/tmp/downloads")

EXPECTED_MIN_COLUMNS = {
    "events": 50,
    "mentions": 10,
    "gkg": 20,
}


def detect_kind(name: str) -> str | None:
    if ".export.CSV.zip" in name:
        return "events"
    if ".mentions.CSV.zip" in name:
        return "mentions"
    if ".gkg.csv.zip" in name:
        return "gkg"
    return None


def validate_file(path: Path, max_rows: int = 1000) -> None:
    kind = detect_kind(path.name)
    if kind is None:
        print("skip", path.name)
        return
    min_cols = EXPECTED_MIN_COLUMNS[kind]
    counts = []
    with zipfile.ZipFile(path) as zf:
        inner = zf.namelist()[0]
        with zf.open(inner) as f:
            text = (line.decode("utf-8", errors="replace") for line in f)
            reader = csv.reader(text, delimiter="\t")
            for i, row in enumerate(reader):
                counts.append(len(row))
                if i + 1 >= max_rows:
                    break
    if not counts:
        raise AssertionError(f"{path.name}: no rows")
    min_seen = min(counts)
    max_seen = max(counts)
    print(path.name, kind, "rows_checked", len(counts), "cols", min_seen, max_seen)
    if min_seen < min_cols:
        raise AssertionError(f"{path.name}: too few columns: {min_seen} < {min_cols}")


def main() -> None:
    files = sorted(DOWNLOAD_DIR.glob("*.zip"))
    if not files:
        raise SystemExit("No zip files found. Run download_sample_gdelt.py first.")
    for path in files:
        validate_file(path)


if __name__ == "__main__":
    main()
```

运行：

```bash
python scripts/validate_raw_gdelt_zip.py
```

通过标准：

```text
每个 zip 至少有行
字段数不低于最低预期
无解压错误
```

注意：字段数最低值只是开发前粗检。正式字段名必须根据 GDELT codebook 映射。

---

## 7. raw → Bronze Parquet 测试

### 7.1 转换 events 样本

创建 `scripts/raw_events_to_parquet_sample.py`：

```python
from __future__ import annotations

import csv
import hashlib
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import polars as pl

DOWNLOAD_DIR = Path("data/tmp/downloads")
OUT_DIR = Path("data/bronze/gdelt_events/date=sample")
OUT_DIR.mkdir(parents=True, exist_ok=True)

EVENT_COLUMNS = [
    "GlobalEventID", "SQLDATE", "MonthYear", "Year", "FractionDate",
    "Actor1Code", "Actor1Name", "Actor1CountryCode", "Actor1KnownGroupCode",
    "Actor1EthnicCode", "Actor1Religion1Code", "Actor1Religion2Code",
    "Actor1Type1Code", "Actor1Type2Code", "Actor1Type3Code",
    "Actor2Code", "Actor2Name", "Actor2CountryCode", "Actor2KnownGroupCode",
    "Actor2EthnicCode", "Actor2Religion1Code", "Actor2Religion2Code",
    "Actor2Type1Code", "Actor2Type2Code", "Actor2Type3Code",
    "IsRootEvent", "EventCode", "EventBaseCode", "EventRootCode",
    "QuadClass", "GoldsteinScale", "NumMentions", "NumSources",
    "NumArticles", "AvgTone",
    "Actor1Geo_Type", "Actor1Geo_FullName", "Actor1Geo_CountryCode",
    "Actor1Geo_ADM1Code", "Actor1Geo_ADM2Code", "Actor1Geo_Lat",
    "Actor1Geo_Long", "Actor1Geo_FeatureID",
    "Actor2Geo_Type", "Actor2Geo_FullName", "Actor2Geo_CountryCode",
    "Actor2Geo_ADM1Code", "Actor2Geo_ADM2Code", "Actor2Geo_Lat",
    "Actor2Geo_Long", "Actor2Geo_FeatureID",
    "ActionGeo_Type", "ActionGeo_FullName", "ActionGeo_CountryCode",
    "ActionGeo_ADM1Code", "ActionGeo_ADM2Code", "ActionGeo_Lat",
    "ActionGeo_Long", "ActionGeo_FeatureID",
    "DATEADDED", "SOURCEURL",
]


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_events_zip(path: Path, max_rows: int = 10000) -> pl.DataFrame:
    rows = []
    with zipfile.ZipFile(path) as zf:
        inner = zf.namelist()[0]
        with zf.open(inner) as f:
            text = (line.decode("utf-8", errors="replace") for line in f)
            reader = csv.reader(text, delimiter="\t")
            for i, row in enumerate(reader):
                if len(row) < len(EVENT_COLUMNS):
                    continue
                rows.append(row[:len(EVENT_COLUMNS)])
                if i + 1 >= max_rows:
                    break
    df = pl.DataFrame(rows, schema=EVENT_COLUMNS, orient="row")
    df = df.with_columns([
        pl.lit(path.name).alias("source_file"),
        pl.lit(file_sha256(path)).alias("source_sha256"),
        pl.lit(datetime.now(timezone.utc).isoformat()).alias("ingest_time_utc"),
    ])
    return df


def main() -> None:
    files = sorted(DOWNLOAD_DIR.glob("*.export.CSV.zip"))
    if not files:
        raise SystemExit("No events zip found")
    df = read_events_zip(files[-1])
    print(df.head())
    out = OUT_DIR / "part-000.parquet"
    df.write_parquet(out, compression="zstd")
    print("wrote", out, "rows", df.height)


if __name__ == "__main__":
    main()
```

运行：

```bash
python scripts/raw_events_to_parquet_sample.py
```

通过标准：

```text
写出 data/bronze/gdelt_events/date=sample/part-000.parquet
行数 > 0
Parquet 文件可读
```

---

## 8. DuckDB 查询 Parquet 测试

### 8.1 直接查 Parquet

```bash
python - <<'PY'
import duckdb
con = duckdb.connect()
con.execute("PRAGMA threads=12")
con.execute("PRAGMA memory_limit='20GB'")
q = """
SELECT
  Actor1CountryCode,
  Actor2CountryCode,
  EventRootCode,
  COUNT(*) AS n,
  AVG(CAST(AvgTone AS DOUBLE)) AS avg_tone
FROM read_parquet('data/bronze/gdelt_events/date=sample/*.parquet')
WHERE Actor1CountryCode IS NOT NULL
GROUP BY 1,2,3
ORDER BY n DESC
LIMIT 20
"""
print(con.execute(q).fetchdf())
PY
```

通过标准：

```text
能返回 DataFrame
无内存错误
无 Parquet 读取错误
```

### 8.2 日期解析测试

```bash
python - <<'PY'
import duckdb
con = duckdb.connect()
q = """
SELECT
  SQLDATE,
  strptime(SQLDATE, '%Y%m%d') AS event_date,
  COUNT(*) AS n
FROM read_parquet('data/bronze/gdelt_events/date=sample/*.parquet')
GROUP BY 1,2
ORDER BY n DESC
LIMIT 5
"""
print(con.execute(q).fetchall())
PY
```

---

## 9. Silver 生成最小测试

### 9.1 建立关系映射文件

创建 `configs/relations/cameo_to_relation.yaml`：

```yaml
relation_taxonomy_version: v1
relations:
  cooperation:
    quad_class: [1, 2]
  verbal_conflict:
    quad_class: [3]
  material_conflict:
    quad_class: [4]
  protest_pressure:
    event_root_codes: ["14"]
```

### 9.2 简化 Silver 转换

```bash
python - <<'PY'
from pathlib import Path
import polars as pl

inp = 'data/bronze/gdelt_events/date=sample/*.parquet'
out_dir = Path('data/silver/world_event/date=sample')
out_dir.mkdir(parents=True, exist_ok=True)

lf = pl.scan_parquet(inp)

def relation_expr():
    return (
        pl.when(pl.col('EventRootCode') == '14').then(pl.lit('protest_pressure'))
        .when(pl.col('QuadClass').cast(pl.Int64, strict=False).is_in([1,2])).then(pl.lit('cooperation'))
        .when(pl.col('QuadClass').cast(pl.Int64, strict=False) == 3).then(pl.lit('verbal_conflict'))
        .when(pl.col('QuadClass').cast(pl.Int64, strict=False) == 4).then(pl.lit('material_conflict'))
        .otherwise(pl.lit('unknown'))
    )

silver = (
    lf.select([
        pl.col('GlobalEventID').alias('event_id'),
        pl.col('SQLDATE').alias('event_date_raw'),
        pl.col('Actor1Name').alias('actor1_raw'),
        pl.col('Actor2Name').alias('actor2_raw'),
        pl.col('Actor1CountryCode').alias('actor1_country'),
        pl.col('Actor2CountryCode').alias('actor2_country'),
        pl.col('EventCode').alias('cameo_code'),
        pl.col('EventBaseCode').alias('cameo_base_code'),
        pl.col('EventRootCode').alias('cameo_root_code'),
        pl.col('QuadClass').cast(pl.Int64, strict=False).alias('quad_class'),
        pl.col('GoldsteinScale').cast(pl.Float64, strict=False).alias('goldstein'),
        pl.col('AvgTone').cast(pl.Float64, strict=False).alias('avg_tone'),
        pl.col('NumMentions').cast(pl.Int64, strict=False).alias('num_mentions'),
        pl.col('NumSources').cast(pl.Int64, strict=False).alias('num_sources'),
        pl.col('NumArticles').cast(pl.Int64, strict=False).alias('num_articles'),
        pl.col('ActionGeo_CountryCode').alias('action_geo_country'),
        pl.col('ActionGeo_Lat').cast(pl.Float64, strict=False).alias('action_geo_lat'),
        pl.col('ActionGeo_Long').cast(pl.Float64, strict=False).alias('action_geo_lon'),
        pl.col('SOURCEURL').alias('source_url'),
    ])
    .with_columns([
        relation_expr().alias('relation_id'),
        pl.lit('sample_param_v1').alias('param_version'),
    ])
)

silver.sink_parquet(out_dir / 'part-000.parquet', compression='zstd')
print('wrote silver')
PY
```

通过标准：

```text
data/silver/world_event/date=sample/part-000.parquet 存在
relation_id 非空
```

---

## 10. Gold 聚合最小测试

```bash
python - <<'PY'
from pathlib import Path
import duckdb

out_dir = Path('data/gold/pair_day_relation/date=sample')
out_dir.mkdir(parents=True, exist_ok=True)

con = duckdb.connect()
con.execute("PRAGMA threads=12")
con.execute("PRAGMA memory_limit='20GB'")

q = """
COPY (
  SELECT
    event_date_raw AS date,
    actor1_country AS src_entity_id,
    actor2_country AS dst_entity_id,
    relation_id,
    1 AS window_days,
    COUNT(*) AS event_count,
    SUM(num_mentions) AS mention_count,
    SUM(num_sources) AS source_count,
    AVG(avg_tone) AS avg_tone,
    SUM(goldstein) AS goldstein_sum,
    SUM(LOG(1 + COALESCE(num_mentions, 0))) AS weighted_score,
    'sample_feature_v1' AS feature_version,
    'sample_param_v1' AS param_version
  FROM read_parquet('data/silver/world_event/date=sample/*.parquet')
  WHERE src_entity_id IS NOT NULL
    AND dst_entity_id IS NOT NULL
    AND relation_id != 'unknown'
  GROUP BY 1,2,3,4
) TO 'data/gold/pair_day_relation/date=sample/part-000.parquet' (FORMAT PARQUET, COMPRESSION ZSTD)
"""
con.execute(q)
print('wrote gold pair relation')

print(con.execute("""
SELECT *
FROM read_parquet('data/gold/pair_day_relation/date=sample/*.parquet')
ORDER BY event_count DESC
LIMIT 10
""").fetchdf())
PY
```

通过标准：

```text
能生成 gold pair relation
能查询 top 10 双边关系
```

---

## 11. SQLite 控制面测试

### 11.1 创建数据库

```bash
python - <<'PY'
import sqlite3
from pathlib import Path

path = Path('data/control/world_control.sqlite')
path.parent.mkdir(parents=True, exist_ok=True)
con = sqlite3.connect(path)
cur = con.cursor()
cur.execute('PRAGMA journal_mode=WAL;')
cur.execute('PRAGMA synchronous=NORMAL;')
cur.execute('PRAGMA busy_timeout=5000;')
cur.execute('PRAGMA foreign_keys=ON;')

cur.execute('''
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
)
''')
cur.execute('''
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
  report_path TEXT
)
''')

con.commit()
print(cur.execute('PRAGMA journal_mode;').fetchone())
con.close()
print('sqlite ok', path)
PY
```

通过标准：

```text
输出 wal
数据库文件存在
```

### 11.2 FTS5 测试

```bash
python - <<'PY'
import sqlite3
con = sqlite3.connect('data/control/world_control.sqlite')
cur = con.cursor()
cur.execute('''
CREATE TABLE IF NOT EXISTS evidence_article (
  rowid INTEGER PRIMARY KEY,
  evidence_id TEXT,
  title TEXT,
  snippet TEXT,
  themes TEXT
)
''')
cur.execute('''
CREATE VIRTUAL TABLE IF NOT EXISTS evidence_article_fts
USING fts5(title, snippet, themes, content='evidence_article', content_rowid='rowid')
''')
cur.execute("INSERT INTO evidence_article(evidence_id,title,snippet,themes) VALUES (?,?,?,?)",
            ('ev1','Central bank raises rates','Inflation pressure remains high','MONETARY_POLICY;INFLATION'))
rowid = cur.lastrowid
cur.execute("INSERT INTO evidence_article_fts(rowid,title,snippet,themes) VALUES (?,?,?,?)",
            (rowid,'Central bank raises rates','Inflation pressure remains high','MONETARY_POLICY;INFLATION'))
con.commit()
print(cur.execute("SELECT title FROM evidence_article_fts WHERE evidence_article_fts MATCH 'inflation'").fetchall())
con.close()
PY
```

通过标准：

```text
能查到 Central bank raises rates
```

---

## 12. BigQuery 认证与 dry-run 验证

此项建议做，但如果暂时没有 Google Cloud 账号，可以先跳过，用 raw files 开发。

### 12.1 安装 CLI

```bash
# 参考 Google Cloud 官方文档安装 gcloud。
# 安装后：
gcloud --version
bq version
```

### 12.2 登录

```bash
gcloud auth application-default login
```

### 12.3 dry-run 查询

```bash
bq query \
  --use_legacy_sql=false \
  --dry_run \
  'SELECT COUNT(*) AS n
   FROM `gdelt-bq.gdeltv2.events_partitioned`
   WHERE _PARTITIONTIME BETWEEN TIMESTAMP("2024-01-01") AND TIMESTAMP("2024-01-02")'
```

通过标准：

```text
不实际扫描或收费运行
返回将处理的数据量估算
```

### 12.4 小样本查询

```bash
bq query \
  --use_legacy_sql=false \
  --max_rows=10 \
  'SELECT GlobalEventID, SQLDATE, Actor1Name, Actor2Name, EventCode, QuadClass, AvgTone, SOURCEURL
   FROM `gdelt-bq.gdeltv2.events_partitioned`
   WHERE _PARTITIONTIME BETWEEN TIMESTAMP("2024-01-01") AND TIMESTAMP("2024-01-02")
   LIMIT 10'
```

### 12.5 Python BigQuery 测试

```python
from google.cloud import bigquery

client = bigquery.Client()
query = """
SELECT GlobalEventID, SQLDATE, Actor1Name, Actor2Name, EventCode, QuadClass, AvgTone, SOURCEURL
FROM `gdelt-bq.gdeltv2.events_partitioned`
WHERE _PARTITIONTIME BETWEEN TIMESTAMP('2024-01-01') AND TIMESTAMP('2024-01-02')
LIMIT 10
"""
job_config = bigquery.QueryJobConfig(dry_run=True, use_query_cache=False)
job = client.query(query, job_config=job_config)
print("bytes", job.total_bytes_processed)
```

---

## 13. DOC API 结构验证

```bash
python - <<'PY'
import httpx
url = "https://api.gdeltproject.org/api/v2/doc/doc"
params = {
    "query": "central bank",
    "mode": "timelinevol",
    "format": "json",
    "timespan": "1d",
}
r = httpx.get(url, params=params, timeout=60)
print(r.url)
print(r.status_code)
print(r.text[:1000])
r.raise_for_status()
PY
```

通过标准：

```text
status_code = 200
返回 JSON 或可解析文本
```

DOC API 只用于探索，不作为主数据源。

---

## 14. FastAPI 最小服务测试

创建 `app/api/main.py`：

```python
from fastapi import FastAPI

app = FastAPI(title="GDELT World Lab", version="0.1.0")

@app.get("/health")
def health():
    return {"status": "ok"}
```

运行：

```bash
uvicorn app.api.main:app --host 127.0.0.1 --port 8000
```

另一个终端：

```bash
curl http://127.0.0.1:8000/health
```

通过标准：

```json
{"status":"ok"}
```

检查 OpenAPI：

```text
http://127.0.0.1:8000/docs
```

注意：开发阶段默认不要绑定 `0.0.0.0`。

---

## 15. Hypothesis DSL schema 验证

创建 `scripts/validate_hypothesis_spec.py`：

```python
from pydantic import BaseModel
from typing import Literal

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
    robustness: dict = {}

sample = {
    "claim": "金融压力叙事上升会预测本币贬值",
    "universe": {
        "entity_type": "country",
        "group": "emerging_markets",
        "start_date": "2018-01-01",
        "end_date": "2026-06-23",
    },
    "feature": {
        "feature_id": "country_financial_stress",
        "window_days": 7,
        "transform": "exposure_adjusted_zscore",
        "lag_days": 1,
    },
    "target": {
        "target_id": "fx_return_usd",
        "horizon_days": 5,
    },
    "model": {
        "type": "panel_regression",
        "fixed_effects": ["country", "date"],
        "controls": ["vix", "dxy"],
    },
    "expected_effect": {"sign": "negative"},
    "validation": {
        "method": "walk_forward",
        "train_start": "2018-01-01",
        "test_start": "2022-01-01",
        "metrics": ["t_stat", "out_of_sample_r2"],
    },
    "robustness": {"placebo": ["shuffle_date", "shuffle_country"]},
}

spec = HypothesisSpec.model_validate(sample)
print(spec.model_dump_json(indent=2))
```

运行：

```bash
python scripts/validate_hypothesis_spec.py
```

通过标准：

```text
输出格式化 JSON
无 ValidationError
```

---

## 16. 端到端最小验证

目标：从真实 GDELT raw 文件生成一个可查询的 Gold 表。

### 16.1 一键脚本目标

创建 `scripts/e2e_sample.py`，应完成：

```text
1. 下载 lastupdate
2. 下载最新 events zip
3. 转 bronze parquet
4. 转 silver world_event
5. 聚合 gold pair_day_relation
6. DuckDB 查询 top relations
7. SQLite 写入 data_snapshot
```

### 16.2 通过标准

```text
下载成功
bronze parquet 行数 > 0
silver parquet 行数 > 0
gold parquet 行数 > 0
DuckDB 查询返回结果
SQLite 中有 data_snapshot 或 ingest_batch 记录
总运行时间 < 10 分钟
峰值内存 < 10GB
磁盘新增 < 2GB
```

---

## 17. 性能基准测试

### 17.1 Parquet 读取速度

```bash
python - <<'PY'
import time, duckdb
con = duckdb.connect()
start = time.time()
n = con.execute("SELECT COUNT(*) FROM read_parquet('data/bronze/gdelt_events/date=sample/*.parquet')").fetchone()[0]
elapsed = time.time() - start
print("rows", n, "seconds", elapsed, "rows/sec", n / max(elapsed, 1e-9))
PY
```

记录到：

```text
data/reports/diagnostics/performance_baseline.md
```

### 17.2 Gold 查询延迟

目标：常见 API 查询应 < 2 秒。

```bash
python - <<'PY'
import time, duckdb
con = duckdb.connect()
q = """
SELECT *
FROM read_parquet('data/gold/pair_day_relation/date=sample/*.parquet')
ORDER BY event_count DESC
LIMIT 100
"""
for i in range(5):
    start = time.time()
    df = con.execute(q).fetchdf()
    print(i, len(df), time.time() - start)
PY
```

---

## 18. 磁盘水位测试

创建脚本：

```bash
python - <<'PY'
import shutil
from pathlib import Path

path = Path('.')
total, used, free = shutil.disk_usage(path)
print('total_gb', total/1024**3)
print('used_gb', used/1024**3)
print('free_gb', free/1024**3)
if free < 180 * 1024**3:
    raise SystemExit('free disk below 180GB: stop heavy jobs')
print('disk ok')
PY
```

此检查应在 worker 每次重任务前执行。

---

## 19. 常见失败与处理

### 19.1 GDELT raw 下载失败

可能原因：

```text
网络代理
DNS 问题
临时服务不可用
HTTP 被拦截
```

处理：

```text
重试 3 次
切换 masterfilelist
手动浏览器访问 URL
记录失败到 ingest_batch
不要让任务无穷重试
```

### 19.2 zip 能下载但不能打开

处理：

```text
检查是否下载到 HTML 错误页
检查 Content-Type
检查文件大小是否异常
重新下载
保留坏文件到 data/tmp/bad_downloads 供诊断
```

### 19.3 字段数不一致

处理：

```text
不要直接丢弃整个文件
记录坏行数量
如果坏行比例 > 阈值，标记 batch failed
如果坏行比例低，记录并跳过坏行
检查 codebook 是否更新
```

### 19.4 DuckDB 内存不足

处理：

```text
降低 PRAGMA memory_limit
确保 temp_directory 在大磁盘
减少日期范围
先聚合后 join
使用 Polars lazy/sink_parquet
不要 fetchdf 大结果到内存
```

### 19.5 SQLite database is locked

处理：

```text
开启 WAL
缩短事务
worker 写入时避免长事务
API 只读连接
设置 busy_timeout
```

### 19.6 BigQuery dry-run 扫描量过大

处理：

```text
缩小日期
减少列
使用 partitioned table
先 LIMIT 不能降低扫描量，必须加 partition filter
不要对 GKG 全字段扫描
```

---

## 20. 开发前 Go / No-Go 判定

### 20.1 Go 条件

满足以下条件可以正式开发：

```text
Python 核心依赖全部可导入
GDELT lastupdate 能访问
至少一个 events zip 能下载和解压
raw events 能转成 Parquet
DuckDB 能查 Parquet
SQLite WAL 和 FTS5 可用
FastAPI health 可访问
磁盘空闲 >= 500GB，最好 >= 700GB
端到端样本能生成 Gold 表
```

### 20.2 Conditional Go

可以继续开发，但需记录风险：

```text
BigQuery 暂不可用，但 raw files 可用
LanceDB 暂不可用，但 FTS5 可用
DOC API 暂不可用，但 Events raw 可用
```

### 20.3 No-Go

以下情况不建议开始正式开发：

```text
磁盘空闲 < 300GB
Python 依赖无法稳定安装
GDELT raw 无法访问且 BigQuery 也不可用
DuckDB 无法读取 Parquet
SQLite WAL 不可用
端到端样本无法跑通
```

---

## 21. 验证报告模板

保存到：

```text
data/reports/diagnostics/pre_dev_validation_YYYYMMDD.md
```

模板：

```markdown
# Pre-development Validation Report

Date: YYYY-MM-DD
Machine: AMD Ryzen 7 8745H / 32GB / 1TB
OS:
Python:

## Hardware
- CPU:
- Memory:
- Disk total:
- Disk free:

## Python dependencies
- duckdb:
- polars:
- pyarrow:
- fastapi:
- pydantic:

## Network
- data.gdeltproject.org: PASS/FAIL
- lastupdate.txt: PASS/FAIL
- masterfilelist.txt: PASS/FAIL
- DOC API: PASS/FAIL

## Raw GDELT sample
- events zip:
- mentions zip:
- gkg zip:
- rows checked:
- field count status:

## Local storage
- bronze parquet: PASS/FAIL
- silver parquet: PASS/FAIL
- gold parquet: PASS/FAIL

## DuckDB
- query parquet: PASS/FAIL
- aggregation: PASS/FAIL
- latency:

## SQLite
- WAL: PASS/FAIL
- FTS5: PASS/FAIL

## BigQuery
- auth: PASS/FAIL/SKIPPED
- dry-run: PASS/FAIL/SKIPPED
- sample query: PASS/FAIL/SKIPPED

## API
- health endpoint: PASS/FAIL

## Go decision
GO / CONDITIONAL GO / NO-GO

## Notes
...
```

---

## 22. 开发前验证输出物

完成验证后，应保留以下文件：

```text
data/reports/diagnostics/pre_dev_validation_YYYYMMDD.md
data/tmp/downloads/*.zip，至少临时保留一个样本
数据样本：data/bronze/gdelt_events/date=sample/part-000.parquet
Silver 样本：data/silver/world_event/date=sample/part-000.parquet
Gold 样本：data/gold/pair_day_relation/date=sample/part-000.parquet
SQLite 控制面：data/control/world_control.sqlite
```

如果磁盘紧张，可以删除 raw zip，但建议保留验证报告和 Parquet 样本。

---

## 23. 官方资料入口

- GDELT Data： https://www.gdeltproject.org/data.html
- GDELT 2.0 发布说明： https://blog.gdeltproject.org/gdelt-2-0-our-global-world-in-realtime/
- GDELT raw / BigQuery / docs 入口： https://www.gdeltproject.org/data.html
- GDELT Event Codebook V2.0： https://data.gdeltproject.org/documentation/GDELT-Event_Codebook-V2.0.pdf
- GDELT DOC 2.0 API： https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/
- GDELT Context 2.0 API： https://blog.gdeltproject.org/announcing-the-gdelt-context-2-0-api/
- GDELT partitioned BigQuery tables： https://blog.gdeltproject.org/announcing-partitioned-gdelt-bigquery-tables/
- BigQuery partitioned tables： https://cloud.google.com/bigquery/docs/partitioned-tables
- DuckDB Parquet： https://duckdb.org/docs/current/data/parquet/overview.html
- Polars 文档： https://docs.pola.rs/
- SQLite WAL： https://sqlite.org/wal.html
- SQLite FTS5： https://sqlite.org/fts5.html
- FastAPI： https://fastapi.tiangolo.com/
- MCP： https://modelcontextprotocol.io/docs/getting-started/intro
- Optuna： https://optuna.readthedocs.io/
- MLflow Tracking： https://mlflow.org/docs/latest/ml/tracking/
- LanceDB： https://docs.lancedb.com/quickstart
