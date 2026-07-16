# Real GDELT probe — 2026-07-16

状态：Development evidence，不代表目标机器最终 GO 结论。

## Observed upstream behavior

- HTTPS `lastupdate.txt` 在当前环境连续返回 502/超时；
- 官方 HTTP 兼容入口成功返回 manifest；
- manifest 最新批次为 `20260716073000`；
- latest export 与 mentions 下载、大小、MD5、ZIP 均验证通过；
- latest GKG 同时出现在 lastupdate 与 masterfilelist，但对象请求返回 HTTP 404；
- 回退到 masterfilelist 中上一完整批次 `20260716071500` 后，GKG 下载成功且大小、MD5、ZIP 验证通过。

这说明生产下载器必须校验对象真实存在，且当一个数据集缺失时回退整个完整批次，不能混合不同批次后假装一致。

## Real sample results

| Dataset | Batch | ZIP bytes | MD5 | Rows | Fields | Result |
|---|---:|---:|---|---:|---:|---|
| Events | 20260716073000 | 59,813 | `eb1155fd75a7f4e3e465aa36978a6aea` | 1,008 | 61 | PASS |
| Mentions | 20260716073000 | 83,846 | `e9a3bb8688e9e89a471772f45aaebcec` | 2,971 | 16 | PASS |
| GKG | 20260716073000 | expected 3,886,127 | `1f21d245c1c402e6cc363743e19a03cf` | — | 27 | FAIL: HTTP 404 |
| GKG fallback | 20260716071500 | 3,291,274 | `7c9e3119281882f3acc5bc6cdfeeaa28` | 787 | 27 | PASS |

## Security note

HTTP fallback is observable and opt-in. Size and MD5 protect against accidental corruption but do not provide modern transport authenticity. The validation report must retain this warning; a trusted HTTPS/BigQuery route remains preferable for production history ingestion.

## Development consequences

1. HTTPS-first, explicit HTTP fallback；
2. atomic `.part` download and rename；
3. size + MD5 + ZIP member/path + field-count validation；
4. masterfile tail range request instead of downloading the full ~120MB manifest；
5. select the newest complete, downloadable batch；
6. preserve failed attempts as evidence rather than silently retrying forever。

## Implemented probe rerun

代码化 probe 在稍后的 `20260716074500` 批次再次运行。该批次三个对象均实际可下载，因此没有触发批次回退：

| Dataset | ZIP bytes | Rows | Fields | Result |
|---|---:|---:|---:|---|
| Events | 66,630 | 1,080 | 61 | PASS |
| Mentions | 87,718 | 2,875 | 16 | PASS |
| GKG | 3,966,654 | 954 | 27 | PASS |

probe 仍观察到 HTTPS 502，并显式记录 HTTP transport warning。三个文件均通过官方大小、官方 MD5、ZIP 安全和字段契约检查，同时生成本地 SHA-256。

## Real minimal pipeline result

以 `20260716074500.export.CSV.zip` 执行真实最小管线：

| Artifact | Rows | Result |
|---|---:|---|
| Bronze `gdelt_events` | 1,080 | PASS |
| Silver `world_event` | 1,080 | PASS |
| Gold `country_day_state` | 69 | PASS |
| Gold `pair_day_relation` | 91 | PASS |

Silver 的 1,080 行对应 1,080 个唯一 `dedupe_key`，没有空 event date。事件日期范围为 2025-07-16 至 2026-07-16，这也证明“摄取批次时间”和“事件发生日期”不能混为同一时间轴。`DATEADDED` 在 DuckDB 验证会话中固定为 UTC，批次时间为 `2026-07-16 07:45:00+00`。
