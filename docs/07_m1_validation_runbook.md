# 07｜M1 开发前验证运行手册

## 目标

在目标机器上证明 Python、磁盘、SQLite、GDELT 端点及列式分析栈可形成最小真实数据闭环。CI 只验证代码，不替代目标机器的 GO/NO-GO 结论。

## 安装

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e '.[data,research,dev]'
```

## 本地门禁

```bash
hello-gdelt preflight --root .
```

报告写入 `reports/m1_preflight_report.json` 和 `reports/m1_preflight_report.md`。报告目录被 `.gitignore` 排除，避免提交机器信息。

## GDELT 网络门禁（下一工作包）

必须验证：

1. `https://data.gdeltproject.org/gdeltv2/lastupdate.txt`；
2. 同一 15 分钟时间戳的 Events、Mentions、GKG 三个 ZIP；
3. Content-Length、实际字节数和 MD5；
4. ZIP 路径安全与 CRC；
5. 抽样字段数：Events 61、Mentions 16、GKG 27；
6. 原始文件到 Bronze Parquet；
7. DuckDB 可读取并生成最小 Gold 聚合。

任何下载器必须设置总字节上限、超时、有限重试和临时文件原子替换，禁止直接解压不受信任路径。

## 当前代码覆盖

- `parse_lastupdate`：严格解析并要求三表时间戳一致；
- `validate_tsv_sample`：检测字段数漂移；
- `run_local_preflight`：Python、64 位、磁盘、核心依赖、SQLite WAL/FTS5、运行目录；
- 单元测试覆盖正常、缺表、不可信主机和 schema drift。

## 门禁解释

- `GO`：全部硬依赖与本地检查通过；
- `CONDITIONAL_GO`：可选研究依赖或非关键接口暂不可用，有明确风险登记；
- `NO_GO`：Python/磁盘/列式栈/SQLite 等硬门槛失败。
