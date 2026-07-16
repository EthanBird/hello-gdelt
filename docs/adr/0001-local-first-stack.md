# ADR 0001｜V1 采用单机嵌入式数据栈

状态：Accepted  
日期：2026-07-16

## Context

目标机器为 1TB SSD、32GB RAM、8 核 16 线程 CPU。V1 需要受控切片、可回放 ETL、交互式分析、实验注册和受限 LLM 调用，但不需要跨机器水平扩展。

## Decision

- Parquet + ZSTD 保存 Bronze/Silver/Gold；
- DuckDB 承担本地 OLAP 与 Gold 聚合；
- Polars/PyArrow 承担流式或批式转换；
- SQLite WAL 承担控制面、lineage 与实验注册；
- FastAPI 提供本地查询；MCP 仅封装白名单能力；
- 默认绑定 `127.0.0.1`；
- 调度优先 APScheduler/systemd timer。

## Consequences

优点是部署简单、备份明确、列裁剪和分区过滤有效；代价是单机并发和内存受限，需要硬性扫描量、线程、临时目录和磁盘水位控制。

在 V1 中不得无 ADR 引入 Kafka、Spark、Flink、Kubernetes、Airflow 或远程数据库服务。
