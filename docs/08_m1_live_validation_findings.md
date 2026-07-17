# 08｜M1 首次真实环境验证发现

验证日期：2026-07-17  
验证环境：GitHub Actions Ubuntu 24.04 / Python 3.11  
性质：云端独立验证环境，不替代用户目标机器门禁

## 1. 已通过项目

在安装 `.[data]` 后，以下检查通过：

- Python 3.11、x86_64；
- HTTPX、Pydantic、PyYAML；
- DuckDB、Polars、PyArrow；
- SQLite WAL；
- SQLite FTS5；
- 数据与报告目录可写。

CI 可用空间约 94GB，低于目标机器协议中的 300GB，因此仅在关闭硬磁盘门禁后得到 `CONDITIONAL_GO`。这不修改目标机器必须保留至少 300GB 空闲空间的规则。

## 2. 首次真实 GDELT 请求结果

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

因此第一次真实闭环被正确裁决为 `NO_GO`，没有关闭 TLS 校验，也没有把未验证数据写入研究层。

## 3. 处置原则

GDELT 官方历史文档长期以 `http://data.gdeltproject.org/...` 发布原始文件地址。为区分“传输层故障”和“数据格式故障”，实现了显式的 legacy HTTP 回退实验，但遵循以下约束：

1. HTTPS 严格校验仍是默认；
2. 只有提供 `--allow-insecure-http` 才允许回退；
3. 报告必须记录 `HTTP_FALLBACK`，不能伪装为安全传输；
4. 按官方清单校验字节数与 MD5；
5. 另计算并保存 SHA-256，供后续复现与跨环境比对；
6. 检查 ZIP 路径、解压大小、压缩比和 CRC；
7. 研究报告必须披露原始传输未认证这一限制；
8. 一旦 GDELT HTTPS 恢复，应重新获取并对照 SHA-256。

MD5 与 SHA-256 可以证明下载后文件是否发生变化，但在清单本身也经 HTTP 取得时，不能单独证明发布者身份。因此 HTTP 结果最多用于 M1 格式和工程闭环，不足以直接形成确认性金融结论。

## 4. 下一门禁

第二次真实样本运行需要回答：

- legacy HTTP 是否仍直接提供清单和三个 ZIP，还是强制跳转到故障 HTTPS；
- Events、EventMentions、GKG 是否保持同一 15 分钟时间戳；
- 文件字节数、MD5、ZIP CRC 和字段数 61/16/27 是否全部通过；
- Polars 是否可生成 ZSTD Parquet；
- DuckDB 行数是否与 Parquet manifest 一致；
- 三个文件的 SHA-256 是否能在另一网络环境复现。

在这些问题有证据前，M1 保持 `NO_GO`。
