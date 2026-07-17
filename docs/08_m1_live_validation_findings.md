# 08｜M1 真实环境验证发现

验证日期：2026-07-17  
验证环境：GitHub Actions Ubuntu 24.04 / Python 3.11.15  
性质：云端独立验证环境，不替代用户目标机器门禁

## 1. 本地分析栈检查

在安装 `.[data]` 后，以下检查通过：

- Python 3.11、x86_64；
- HTTPX、Pydantic、PyYAML；
- DuckDB、Polars、PyArrow；
- SQLite WAL；
- SQLite FTS5；
- 数据与报告目录可写。

CI 可用空间约 94GB，低于目标机器协议中的 300GB，因此关闭 CI 的硬磁盘门禁后，本地栈结论为 `CONDITIONAL_GO`。这不修改目标机器必须保留至少 300GB 空闲空间的规则。该工作流只安装数据依赖，未安装 `statsmodels`，统计研究栈仍须在后续模型门禁中单独验证。

## 2. HTTPS 严格请求结果

严格访问：

```text
https://data.gdeltproject.org/gdeltv2/lastupdate.txt
```

在 2026-07-17 的 GitHub Actions 环境返回 TLS 主机名校验失败：

```text
SSL: CERTIFICATE_VERIFY_FAILED
certificate verify failed: Hostname mismatch,
certificate is not valid for 'data.gdeltproject.org'
```

第一次真实闭环因此正确裁决为 `NO_GO`：没有关闭 TLS 校验，也没有把该次请求视为有效数据输入。

## 3. 显式 legacy HTTP 工程验证

为区分“GDELT 传输层故障”和“解析/列式工程故障”，第二次运行显式提供：

```bash
hello-gdelt gdelt-sample --allow-insecure-http
```

HTTPS 失败后，程序才回退至：

```text
http://data.gdeltproject.org/gdeltv2/lastupdate.txt
```

取得的清单时间戳为 `20260717054500`。三个数据集保持同一 15 分钟时间戳，并完成从 ZIP 到 Bronze Parquet 再到 DuckDB 的真实闭环：

| 数据集 | ZIP 字节 | 抽样/全文件行数 | 字段数 | 坏行 | Parquet 行 | DuckDB 行 |
|---|---:|---:|---:|---:|---:|---:|
| Events | 44,283 | 695 | 61 | 0 | 695 | 695 |
| GKG | 3,373,100 | 864 | 27 | 0 | 864 | 864 |
| EventMentions | 65,814 | 2,181 | 16 | 0 | 2,181 | 2,181 |

由于三个文件均少于 10,000 行，本次“抽样字段检查”实际覆盖了文件全部记录。程序同时验证：

- 清单字节数与实际下载字节一致；
- 清单 MD5 与实际文件一致；
- 另生成 SHA-256 复现指纹；
- ZIP 单文件路径安全；
- 解压大小与压缩比在上限内；
- ZIP CRC 通过；
- Events / Mentions / GKG 分别严格为 61 / 16 / 27 列；
- ZSTD Parquet 成功写入；
- DuckDB 读取行数与 Parquet manifest 一致。

净化后的证据记录保存在：

```text
evidence/m1_gdelt_sample_20260717054500.json
```

其中不包含 CI 临时目录或原始数据，只保留时间戳、大小、MD5、SHA-256、字段数和行数。

## 4. 传输与证据边界

显式 HTTP 回退遵循：

1. HTTPS 严格校验始终是默认；
2. 只有提供 `--allow-insecure-http` 才允许回退；
3. 报告记录 `HTTP_FALLBACK`，不得伪装为安全传输；
4. 按清单验证字节数与 MD5；
5. 另计算 SHA-256，供跨环境比对；
6. 研究报告披露原始传输未认证；
7. 一旦 GDELT HTTPS 恢复，应重新获取并对照 SHA-256。

MD5、SHA-256 和 CRC 可以证明取得后的文件完整性，但在清单本身也经 HTTP 取得时，不能单独认证发布者身份。因此该结果证明的是：

> GDELT 当前真实三表格式与本项目下载、解压、字段契约、Parquet 和 DuckDB 工程链路可以工作。

它不证明：

- HTTP 内容必然未被中间人替换；
- 历史数据可完整回填；
- 媒体数据不存在编码偏差；
- 任一新闻—市场假设得到支持。

## 5. 门禁裁决

分层裁决如下：

| 门禁 | 裁决 | 原因 |
|---|---|---|
| 云端本地分析栈 | `CONDITIONAL_GO` | 列式栈与 SQLite 通过，但磁盘少于 300GB、未安装研究统计栈 |
| 单个最新 GDELT 三表工程闭环 | `GO` | 三表同时间戳，完整性、字段、Parquet 与 DuckDB 全部通过 |
| GDELT 认证传输 | `NO_GO` | HTTPS 证书主机名不匹配，HTTP 无发布者认证 |
| 项目整体 M1 | `CONDITIONAL_GO` | 可进入受控数据地基开发，但目标机器和跨环境哈希复验尚未完成 |
| 确认性市场研究 | `NO_GO` | 历史新闻、合法市场数据、时点日历及最终样本尚未就绪 |

## 6. 下一门禁

下一步必须完成：

- 在用户目标机器运行同一 preflight，确认至少 300GB 空闲及完整统计依赖；
- 在另一网络环境对相邻时间戳 GDELT 文件复验 SHA-256 和字段契约；
- 实现可重入历史清单、manifest 和断点恢复；
- 将正式 GDELT 字段语义映射到 Silver 层，而不是长期使用通用原始列名；
- 建立市场日历、时区和 `PRE_OPEN / IN_SESSION / POST_CLOSE` 对齐契约；
- 对公开或已许可的第一批市场数据完成时点和复权审计。

在这些门禁通过前，不运行 96 项确认性市场假设，也不生成任何“新闻可以预测资产”的结论。
