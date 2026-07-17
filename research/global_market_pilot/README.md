# Global Market Pilot

首轮真实数据试验，验证 GDELT 新闻因子与多市场收益/波动研究管线。

```bash
python -m pip install -e . pandas statsmodels matplotlib yfinance requests
RESEARCH_OUTPUT=research_output_global_market \
  python research/global_market_pilot/run_pilot.py
```

输出包括行情与 GDELT 源审计、分析面板、机器可读结果、中文阶段报告和图表。

该试验使用 Yahoo Finance 作为 C 级公开行情源，只用于验证研究工程和初步规律。完整论文将使用交易所、监管机构、基准管理机构或明确许可的数据源进行确认性复核。
