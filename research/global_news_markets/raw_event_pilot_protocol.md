# GDELT 每日 Event 原始文件接入与市场研究 Pilot

版本：v1.0-pre-run  
目的：替代被撤回的 DOC API 一年期方案，验证适合单机长期回放的 GDELT 原始 Event 数据路径。

## 数据源

- 日文件：`https://data.gdeltproject.org/events/YYYYMMDD.export.CSV.zip`；
- 官方校验表：`https://data.gdeltproject.org/events/md5sums`；
- 文件内容：无表头、制表符分隔的 58 列 Event 记录；
- 本 Pilot 只处理 Event 表，不把 Event 当作文章全文或 GKG 主题数据。

## Pilot 日期

首次执行固定为 2025-07-18 至 2025-07-31，共 14 个自然日。该窗口仅用于数据质量与工程验证，不进行资产价格显著性结论。

选择该窗口是因为它位于原 Stage 1 的起点，可与后续市场数据对齐，同时规模约为百余 MB 压缩数据，适合 CI 与单机测试。

## 强制数据门禁

每个日期必须记录：

1. 请求 URL 和获取时间；
2. ZIP 字节数；
3. 官方 MD5 与本地 MD5；
4. 本地 SHA-256；
5. ZIP 完整性；
6. 解压后文件名、行数和字段数分布；
7. SQLDATE 与文件日期一致率；
8. 重复 GLOBALEVENTID 数量；
9. 关键字段缺失率；
10. 坏记录隔离数量。

官方 MD5 不匹配、ZIP 损坏、58 列比例低于 99.9% 或 SQLDATE 一致率低于 99%，该日不得进入 Silver。

## Silver 事件契约

Pilot 保留：

- GLOBALEVENTID、SQLDATE、DATEADDED；
- Actor1/Actor2 code、name、country；
- EventCode、EventBaseCode、EventRootCode、QuadClass；
- GoldsteinScale、NumMentions、NumSources、NumArticles、AvgTone；
- ActionGeo country/lat/long；
- SOURCEURL 与 source domain。

## Gold 日频特征

### 全球日状态

- event_count；
- mention/source/article totals；
- verbal/material cooperation share；
- verbal/material conflict share；
- mention-weighted Tone；
- mention-weighted Goldstein；
- unique source domain count；
- abnormal event and mention volume。

### 国家日状态

按 Actor1、Actor2 与 ActionGeo 三种角色分别统计：事件数、冲突/合作、Tone、Goldstein、提及量与来源数。

### 双边关系

按 Actor1CountryCode → Actor2CountryCode × EventRootCode 聚合，保留方向、QuadClass 和贡献最大的证据 URL。

## 市场研究边界

Pilot 完成后才允许扩大到 2015—2026。Event 数据可以支持地缘冲突、外交、制裁、抗议、合作等关系研究，但不能替代 GKG 的货币政策、公司、行业和主题语义。后续将独立接入 EventMentions 与 GKG，并记录 join 覆盖率。
