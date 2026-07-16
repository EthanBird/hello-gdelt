# 01｜GDELT 可计算世界模型：数学建模定义

版本：v0.1  
日期：2026-06-23  
目标运行环境：单机研究型系统，1TB 磁盘、32GB 内存、8 核 16 线程 CPU  
核心思想：把 GDELT 视为“媒体观测到的世界状态流”，在其上构建可调参、可验证、可被大模型调用的动态关系模型。

---

## 0. 一句话定义

本项目要构建的不是一个“事实真相数据库”，而是一个：

> **基于 GDELT 新闻观测数据的、可调参的、概率化的、动态异质关系世界模型。**

它的目标是把全球新闻中的事件、主体、地点、主题、情绪、来源、报道强度和叙事变化转化为一组可计算对象：

```text
实体状态
双边关系
主题压力
叙事扩散
风险指数
政策倾向
可验证假设
实验结果
失败记忆
```

最终系统应该支持下面这种循环：

```text
GDELT 观测数据
  → 动态世界状态
  → 大模型提出数学假设
  → 系统自动构造特征与验证数据集
  → 滚动回测与稳健性检验
  → 接受 / 拒绝 / 暂无结论
  → 假设修正与版本化记忆
```

---

## 1. 基本哲学：Observed World，不是 True World

### 1.1 GDELT 的角色

GDELT 监测全球新闻报道，并将其中的事件、人物、组织、地点、主题和情绪等转成结构化数据。工程上应把它视为：

```text
全球媒体报道流的结构化观测层
```

而不是：

```text
真实世界事件全集
```

因此所有指标命名都应强调“媒体观测”或“叙事压力”：

```text
推荐命名：
- observed_world_state
- media_observed_relation
- narrative_pressure
- gdelt_risk_pressure
- gdelt_policy_bias

避免命名：
- true_world_state
- real_risk
- actual_policy_intent
- objective_country_risk
```

### 1.2 为什么这样定义

GDELT 的优势：

```text
覆盖范围广
更新频率高
跨语言
有事件编码
有主题和情绪
可追溯到新闻 URL
适合构造高频世界状态代理变量
```

GDELT 的限制：

```text
媒体覆盖偏差
重复报道
机器事件编码误差
实体识别误差
地理编码误差
语气 Tone 不是金融情绪专用指标
GoldsteinScale 只取决于事件类型，不理解具体上下文
```

所以本模型的基本假设是：

\[
\text{GDELT Observation}_{t}
= f(\text{Latent World State}_{t}, \text{Media System}_{t}, \text{Coder Noise}_{t})
\]

其中我们真正能直接看到的是左边，右边的真实世界状态只能通过概率模型推断。

---

## 2. 世界模型总定义

定义时间 \(t\) 的世界状态为：

\[
\mathcal{W}_t = (G_t, X_t, Z_t, \Theta_t, \mathcal{H}_t, \mathcal{EVID}_t)
\]

其中：

| 符号 | 含义 |
|---|---|
| \(G_t\) | 时间 \(t\) 的动态多关系图 |
| \(X_t\) | 可观测特征矩阵，来自 GDELT、市场、宏观、地理、制度等数据 |
| \(Z_t\) | 不可直接观测的潜在世界状态 |
| \(\Theta_t\) | 参数集合，包括边权重、归一化、状态转移、模型参数 |
| \(\mathcal{H}_t\) | 假设集合，由人或大模型提出并等待验证 |
| \(\mathcal{EVID}_t\) | 证据集合，包括文章 URL、标题、摘要、来源、贡献度 |

动态图定义为：

\[
G_t = (V_t, E_t, R, K, S, A_t)
\]

| 符号 | 含义 |
|---|---|
| \(V_t\) | 实体集合，例如国家、央行、公司、组织、人物、地区 |
| \(E_t\) | 时间 \(t\) 的边集合 |
| \(R\) | 关系类型集合，例如合作、冲突、制裁、抗议、金融压力 |
| \(K\) | 主题集合，例如通胀、债务、战争、能源、央行、选举 |
| \(S\) | 来源集合，例如媒体域名、来源国家、语言、转载链 |
| \(A_t\) | 多关系邻接张量或稀疏边表 |

单条边定义为：

\[
e = (i, j, r, k, t, w, loc, src, tone, confidence, evidence)
\]

含义是：

```text
实体 i 在时间 t 对实体 j 发生或被媒体描述为发生了关系 r，
该关系属于主题 k，强度为 w，发生地点 loc，
由来源 src 报道，语调为 tone，可信度或抽取置信度为 confidence，
证据为一组文章 URL 或 GDELT DocumentIdentifier。
```

---

## 3. 实体层定义

### 3.1 实体类型

第一版建议只做国家级实体，再逐步扩展：

```text
V0：国家 country
V1：国家 + 央行 + 国际组织
V2：国家 + 央行 + 政府部门 + 主要公司 + 政治人物
V3：多粒度实体，含城市、港口、军队、产业、商品、货币
```

实体类型：

| entity_type | 示例 | 第一版是否需要 |
|---|---|---|
| country | USA, CHN, JPN, TUR | 必须 |
| central_bank | FED, ECB, BOJ, PBOC | 建议 |
| international_org | IMF, NATO, UN, EU | 建议 |
| government | US Treasury, China MFA | 可选 |
| person | Powell, Xi, Erdogan | 后续 |
| company | Apple, Gazprom, TSMC | 后续 |
| market_asset | USD, JPY, Gold, Brent | 可选 |
| location | Kyiv, Taiwan Strait | 后续 |

### 3.2 实体版本化

实体映射不能覆盖历史。必须支持：

```text
entity_id
canonical_name
entity_type
country_code
aliases
valid_from
valid_to
confidence
source
```

例如：

```text
Fed, Federal Reserve, FOMC, Powell
→ CENTRAL_BANK_US

USA, United States, Washington, US Government
→ COUNTRY_USA 或 GOVERNMENT_USA，按任务区分
```

### 3.3 实体解析函数

定义实体解析函数：

\[
\pi(a, t) \rightarrow v
\]

其中 \(a\) 是 GDELT 原始 Actor、Person、Organization、Location 字段，\(t\) 是时间，\(v\) 是系统内部实体 ID。

如果无法确定实体，则返回：

```text
UNKNOWN
AMBIGUOUS
RAW_ONLY
```

并记录置信度。

---

## 4. 关系层定义

### 4.1 三类关系

本模型中关系分三类。

#### A. 事件关系：Actor → Actor

来自 GDELT Events。

示例：

\[
USA \xrightarrow{verbal\_conflict} CHN
\]

\[
RUS \xrightarrow{material\_conflict} UKR
\]

适合表示：

```text
外交批评
威胁
军事冲突
合作
援助
谈判
制裁
抗议
镇压
```

#### B. 叙事关系：Entity ↔ Theme

来自 GDELT GKG Themes / Tone / Organizations / Persons / Locations。

示例：

\[
Turkey \leftrightarrow Inflation
\]

\[
Japan \leftrightarrow Monetary\ Easing
\]

适合表示：

```text
金融压力叙事
政策叙事
战争叙事
能源叙事
社会不稳定叙事
央行鹰鸽叙事
```

#### C. 来源传播关系：Source / Region → Narrative

来自来源国家、来源域名、语言、时间序列。

示例：

\[
LocalMedia_{TR} \rightarrow GlobalEnglishMedia \rightarrow FXMarket
\]

适合表示：

```text
本地媒体是否领先国际媒体
英文媒体是否放大某类风险
某些来源是否重复转载
叙事从区域扩散到全球的速度
```

---

## 5. 关系分类体系

### 5.1 内部关系 taxonomy

第一版建议用 10–12 类关系，而不是直接使用全部 CAMEO code。

```yaml
relation_taxonomy_version: v1
relations:
  cooperation:
    description: 外交、经济、人道、军事合作或支持
  verbal_conflict:
    description: 批评、谴责、威胁、指责、外交摩擦
  material_conflict:
    description: 暴力、战争、军事行动、恐袭、武装冲突
  sanction_pressure:
    description: 制裁、禁运、资产冻结、出口管制、关税惩罚
  protest_pressure:
    description: 抗议、罢工、骚乱、社会动员
  repression_pressure:
    description: 镇压、逮捕、限制、强制驱散
  financial_stress:
    description: 货币危机、债务风险、银行风险、资本外逃、IMF
  monetary_policy_bias:
    description: 加息、降息、紧缩、宽松、通胀、增长、央行沟通
  energy_security:
    description: 能源供应、油气价格、管道、产能、禁运
  trade_tension:
    description: 贸易争端、关税、出口限制、供应链摩擦
  political_uncertainty:
    description: 选举、政府危机、政策不确定性、领导人更替
  humanitarian_stress:
    description: 灾害、难民、粮食、疫情、人道危机
```

### 5.2 CAMEO 映射原则

第一版可以采用粗粒度：

```text
QuadClass 1/2 → cooperation
QuadClass 3 → verbal_conflict
QuadClass 4 → material_conflict
EventRootCode 14 → protest_pressure
EventRootCode 17/18/19/20 → coercion/material_conflict，按 code 再细分
```

但注意：

```text
QuadClass 只能粗分关系方向，不能替代具体研究定义。
GoldsteinScale 只基于事件类型，不考虑规模、上下文和真实影响。
EventCode 层级越细，语义越准，但噪声和稀疏性越强。
```

---

## 6. 时间定义

### 6.1 时间粒度

可用粒度：

```text
15min：接近 GDELT 原始更新粒度；适合实时告警，不适合单机长期全量
1h：适合突发事件分析
1d：默认推荐；适合金融、宏观、国家关系、回测
1w：适合政策和地缘趋势
1m：适合阵营、结构性变化和社区分析
```

第一版默认：

```yaml
time_bucket: 1d
windows: [1, 7, 14, 30, 90]
decay_half_life_days: 14
```

### 6.2 时间窗口函数

滚动窗口聚合：

\[
Y_{t}^{(L)} = \sum_{\tau=t-L+1}^{t} y_\tau
\]

指数衰减聚合：

\[
Y_{t}^{(\tau)} = \sum_{e:t_e \le t} y_e \cdot \exp[-(t-t_e)/\tau]
\]

半衰期 \(h\) 与 \(\tau\) 的关系：

\[
\tau = \frac{h}{\ln 2}
\]

---

## 7. 边权重定义

### 7.1 单事件权重

对每个 GDELT 事件 \(e\)，定义基础权重：

\[
w_e =
\log(1+M_e)^\alpha
\cdot
(1+S_e)^\beta
\cdot
\psi(G_e)
\cdot
\phi(T_e)
\cdot
\omega(src_e)
\cdot
\delta(e)
\cdot
d(t-t_e)
\]

其中：

| 符号 | 含义 |
|---|---|
| \(M_e\) | NumMentions 或 ArticleCount |
| \(S_e\) | NumSources 或 source diversity |
| \(G_e\) | GoldsteinScale |
| \(T_e\) | AvgTone 或 GKG Tone |
| \(\omega(src_e)\) | 来源权重 |
| \(\delta(e)\) | 去重/置信度/质量惩罚 |
| \(d(t-t_e)\) | 时间衰减 |
| \(\alpha,\beta\) | 可调参数 |

推荐默认值：

```yaml
mentions_power: 0.5
sources_power: 0.7
goldstein_weight: 0.6
tone_weight: 0.4
source_diversity_weight: 0.5
duplicate_penalty: 0.6
decay_half_life_days: 14
```

### 7.2 Mention 非线性

避免热门事件重复报道过度放大：

\[
f(M_e)=\log(1+M_e)^\alpha
\]

或：

\[
f(M_e)=\min(\log(1+M_e), cap)
\]

### 7.3 来源多样性

如果同一事件被 20 个同一集团媒体转载，不应等同于 20 个独立来源。

定义来源多样性：

\[
D_e = \frac{1}{\sum_s p_s^2}
\]

其中 \(p_s\) 是来源域名、来源国家或媒体集团占比。这个值类似有效来源数。

### 7.4 Tone 变换

GDELT Tone 通常范围较大，但大多数新闻集中在小范围。不要直接线性使用。

可选变换：

\[
\phi(T_e)=\tanh(-T_e / c)
\]

风险方向取负号，因为 tone 越负，风险贡献越高。

推荐：

```yaml
tone_scale_c: 10
risk_tone_transform: tanh_negative
```

### 7.5 Goldstein 变换

GoldsteinScale 对冲突/合作方向有帮助，但不要机械解释为真实冲击大小。

冲突压力可以用：

\[
\psi(G_e)=\max(0, -G_e/10)
\]

合作压力可以用：

\[
\psi(G_e)=\max(0, G_e/10)
\]

如果关系类型已经决定方向，也可以仅作为强度调节项：

\[
\psi(G_e)=1+\lambda \cdot |G_e|/10
\]

---

## 8. 曝光归一化

### 8.1 为什么必须归一化

不能直接比较新闻数量，因为：

```text
大国报道天然多
英语国家报道天然多
战争国家会长期高频出现
周末和假日新闻总量变化
某些来源机器转载多
```

因此边权重必须相对化。

### 8.2 实体曝光归一化

定义实体 \(i\) 在时间 \(t\) 的总曝光：

\[
C_{i,t}=\sum_{e: i\in e} f(M_e)
\]

双边关系归一化：

\[
\tilde{Y}_{ijr,t}=
\frac{Y_{ijr,t}}
{\epsilon+\sqrt{C_{i,t}C_{j,t}}}
\]

单国主题归一化：

\[
\tilde{Y}_{ik,t}=
\frac{Y_{ik,t}}
{\epsilon+C_{i,t}}
\]

### 8.3 全局新闻量归一化

定义全局曝光：

\[
G_t=\sum_e f(M_e)
\]

某主题全球热度：

\[
ThemeShare_{k,t}=\frac{Y_{k,t}}{G_t+\epsilon}
\]

### 8.4 季节性标准化

标准化到异常值：

\[
A_{ijr,t}=\frac{\tilde{Y}_{ijr,t}-\mu_{ijr,season}}{\sigma_{ijr,season}+\epsilon}
\]

其中 \(season\) 可以是：

```text
过去 365 天滚动窗口
同星期几
同月份
剔除最近 7 天的历史窗口
```

第一版推荐：

```yaml
zscore_lookback_days: 365
zscore_min_periods: 90
exclude_recent_days: 7
winsorize_quantiles: [0.01, 0.99]
```

---

## 9. 核心状态变量定义

### 9.1 国家风险压力：Country Risk Pressure

\[
Risk_c(t)=
\theta_1 FinancialStress_c(t)+
\theta_2 PoliticalUnrest_c(t)+
\theta_3 ConflictExposure_c(t)+
\theta_4 NegativeTone_c(t)+
\theta_5 CapitalFlightNarrative_c(t)+
\theta_6 ExternalShock_c(t)
\]

推荐分项：

```text
financial_stress_narrative
social_unrest_pressure
external_conflict_pressure
negative_tone_pressure
policy_uncertainty_pressure
capital_flight_narrative
currency_crisis_narrative
debt_stress_narrative
```

每个分项都是 exposure-adjusted z-score。

### 9.2 双边紧张度：Bilateral Tension

\[
Tension_{ij}(t)=
\theta_1 VerbalConflict_{ij}(t)+
\theta_2 MaterialConflict_{ij}(t)+
\theta_3 SanctionPressure_{ij}(t)+
\theta_4 TradeTension_{ij}(t)-
\theta_5 Cooperation_{ij}(t)
\]

注意方向：

```text
Tension_ij 不一定等于 Tension_ji
可以另定义 symmetric tension：
TensionSym_ij = Tension_ij + Tension_ji
```

### 9.3 货币政策倾向：Monetary Policy Bias

定义媒体感知的政策倾向：

\[
MPBias_c(t)=
Hawkish_c(t)-Dovish_c(t)+
InflationConcern_c(t)-GrowthConcern_c(t)+
CurrencyDefense_c(t)
\]

鹰派分项：

```text
rate hike
tightening
restrictive policy
inflation pressure
higher for longer
policy normalization
currency defense
central bank credibility
```

鸽派分项：

```text
rate cut
easing
stimulus
recession risk
growth slowdown
unemployment
liquidity injection
credit support
```

强烈建议在句子级或上下文级处理否定词：

```text
rate cut expected       → 鸽派
rate cut unlikely       → 鹰派或非鸽派
inflation falling       → 鸽派
inflation remains high  → 鹰派
```

### 9.4 政策不确定性：Policy Uncertainty

\[
PolicyUncertainty_c(t)=
z(uncertain + unclear + divided + surprise + unexpected + policy path + guidance)
\]

用途：

```text
预测短端利率波动
解释汇率波动
央行会议前风险定价
识别政策转折期
```

### 9.5 媒体关注冲击：Media Attention Shock

\[
AttentionShock_{i,t}=\frac{C_{i,t}-\mu_{i,t}^{hist}}{\sigma_{i,t}^{hist}+\epsilon}
\]

用途：

```text
识别突发事件
剔除单纯关注度上升造成的假信号
作为其他指标的控制变量
```

---

## 10. 多关系动态张量模型

### 10.1 稀疏张量表示

理论上可以定义：

\[
A_t \in \mathbb{R}^{N\times N\times R}
\]

其中：

\[
A_{ijr,t}
\]

表示时间 \(t\)、实体 \(i\) 到实体 \(j\)、关系 \(r\) 的强度。

加入主题后：

\[
A_t \in \mathbb{R}^{N\times N\times R\times K}
\]

但工程上必须使用稀疏表：

```text
(date, src_entity_id, dst_entity_id, relation_id, theme_id, value, uncertainty)
```

不要落盘 dense tensor。

### 10.2 负二项观测模型

新闻事件计数通常过度离散，因此优先用负二项分布：

\[
Y_{ijr,t}\sim \text{NegBinom}(E_{ij,t}\lambda_{ijr,t}, \kappa_r)
\]

其中：

```text
Y_ijr,t：观测事件数或加权事件数
E_ij,t：曝光项 offset
λ_ijr,t：真实关系强度
κ_r：过度离散参数
```

强度函数：

\[
\log \lambda_{ijr,t}=
\alpha_r+a_{i,r}^{out}+b_{j,r}^{in}+u_{i,t}^{\top}R_ru_{j,t}+\gamma_r^{\top}X_{ij,t}+\rho_r^{\top}H_{ijr,t}
\]

含义：

```text
α_r：关系类型基准强度
a_out：发出方倾向
b_in：承受方倾向
u_i,t：实体潜在状态
R_r：关系类型交互矩阵
X_ij,t：外部协变量
H_ijr,t：历史关系特征
```

### 10.3 潜在状态转移

\[
u_{i,t}=F u_{i,t-1}+B x_{i,t}+\eta_{i,t}
\]

\[
\eta_{i,t}\sim\mathcal{N}(0,Q)
\]

潜变量可以解释为：

```text
domestic_risk
external_tension
policy_hawkishness
social_unrest
financial_stress
diplomatic_isolation
growth_pessimism
```

第一版可不训练完整潜变量模型，而是用可解释指标近似。

---

## 11. 单机优先的简化模型路径

### 11.1 第一阶段：指数 + 面板回归

这是第一版最稳的模型。

构造指标：

\[
Risk_{c,t}=\sum_m \theta_m Feature_{c,m,t}
\]

验证：

\[
FXReturn_{c,t+h}=\alpha_c+\delta_t+\beta Risk_{c,t}+\Gamma Controls_{c,t}+\epsilon_{c,t+h}
\]

其中：

```text
α_c：国家固定效应
δ_t：日期固定效应
Controls：VIX、DXY、利差、商品价格、股市等
h：预测 horizon，例如 1、5、20 天
```

### 11.2 第二阶段：离散事件传播模型

用离散时间近似 Hawkes：

\[
Y_{ij,r,t+h}=\alpha+\sum_{r'}\sum_{\ell=1}^{L}\beta_{r',\ell}Y_{ij,r',t-\ell}+\gamma X_{ij,t}+\epsilon
\]

问题示例：

```text
verbal_conflict 是否领先 material_conflict？
sanction_pressure 是否领先 currency_stress？
protest_pressure 是否领先 policy_easing？
energy_security 是否领先 inflation_concern？
```

### 11.3 第三阶段：轻量状态空间模型

观测方程：

\[
x_{c,t}=\Lambda z_{c,t}+\epsilon_{c,t}
\]

状态方程：

\[
z_{c,t}=\rho z_{c,t-1}+B u_{c,t}+\eta_{c,t}
\]

第一版实现方式：

```text
指数平滑
Kalman filter
动态 PCA
rolling regression
```

### 11.4 第四阶段：月度图结构

每月构建国家关系图：

```text
nodes: countries
edges: relation scores
weights: exposure-adjusted monthly scores
```

计算：

```text
centrality
community
bilateral tension cluster
narrative similarity
regime shift
```

---

## 12. 假设系统的数学定义

### 12.1 假设对象

一个假设定义为：

\[
H=(C,F,T,M,V,D)
\]

| 符号 | 含义 |
|---|---|
| \(C\) | 自然语言 claim |
| \(F\) | 特征定义 feature |
| \(T\) | 目标变量 target |
| \(M\) | 统计模型 |
| \(V\) | 验证方案 |
| \(D\) | 决策规则 |

### 12.2 假设 DSL 示例

```yaml
hypothesis_id: auto
claim: >
  新兴市场国家的 GDELT 金融压力叙事上升，会在 5 个交易日内预测本币兑美元贬值。
universe:
  entity_type: country
  group: emerging_markets
  start_date: "2018-01-01"
  end_date: "2026-06-23"
feature:
  feature_id: country_financial_stress
  window_days: 7
  transform: exposure_adjusted_zscore
  lag_days: 1
target:
  target_id: fx_return_usd
  horizon_days: 5
model:
  type: panel_regression
  fixed_effects: [country, date]
  controls: [vix, dxy, rate_differential]
expected_effect:
  sign: negative
validation:
  method: walk_forward
  train_start: "2018-01-01"
  test_start: "2022-01-01"
  metrics: [t_stat, out_of_sample_r2, directional_accuracy]
robustness:
  placebo: [shuffle_date, shuffle_country, alternative_window_14d]
multiple_testing:
  method: bh_fdr
```

### 12.3 假设编译成方程

上面的 DSL 编译为：

\[
FXReturn_{c,t+5}=\alpha_c+\delta_t+\beta FinancialStress_{c,t}^{7d}+\Gamma Controls_{c,t}+\epsilon_{c,t+5}
\]

检验：

\[
H_0:\beta=0
\]

\[
H_1:\beta<0
\]

---

## 13. 动态验证流程

### 13.1 Walk-forward 验证

不要随机切分。时间序列应使用滚动训练：

```text
Train: 2018-01-01 ~ 2021-12-31
Test : 2022-01-01 ~ 2022-06-30

Train: 2018-01-01 ~ 2022-06-30
Test : 2022-07-01 ~ 2022-12-31

继续滚动……
```

### 13.2 验证指标

预测类：

```text
out_of_sample_r2
rmse
mae
log_loss
auc
directional_accuracy
hit_ratio
information_coefficient
```

解释类：

```text
coefficient_sign
coefficient_t_stat
p_value
q_value
confidence_interval
rolling_stability
```

校准类：

```text
calibration_slope
brier_score
probability_bucket_accuracy
```

复杂度惩罚：

```text
num_features
num_params
runtime_seconds
query_bytes
memory_peak_gb
```

### 13.3 综合评分

\[
Score =
\lambda_1 PredictivePower+
\lambda_2 Calibration+
\lambda_3 Stability-
\lambda_4 Complexity-
\lambda_5 DataCost
\]

默认权重：

```yaml
predictive_power: 0.35
calibration: 0.20
stability: 0.25
complexity: 0.10
data_cost: 0.10
```

### 13.4 决策状态

```text
draft：草稿
compiled：已通过语法检查
running：正在运行
supported：通过预定义决策规则
rejected：未通过，且方向或效果明确失败
inconclusive：结果不足或不稳定
promoted_to_candidate_factor：进入候选因子库
deprecated：被后续假设替代
```

### 13.5 多重检验

大模型会不断提出假设，所以必须控制多重检验。

默认方法：

```text
Benjamini-Hochberg FDR
```

记录：

```text
raw p-value
adjusted q-value
number_of_tests_in_family
hypothesis_family_id
```

---

## 14. 稳健性检验

每个 supported 之前必须做：

```text
日期打乱 placebo
国家打乱 placebo
主题打乱 placebo
替代窗口：7d、14d、30d
替代归一化：raw share、exposure-adjusted、zscore
替代来源：本地媒体、国际媒体、英文媒体、非英文媒体
剔除极端事件窗口
剔除单一国家或单一区域
训练/测试窗口滚动
```

如果只在一个切片中成立，状态应为：

```text
inconclusive
```

而不是：

```text
supported
```

---

## 15. 反事实与失败记忆

系统必须保存失败假设。

失败原因分类：

```text
no_signal：没有统计信号
wrong_sign：方向与预期相反
unstable：滚动窗口不稳定
overfit：训练好、测试差
placebo_fail：安慰剂也显著
data_quality：数据质量不足
cost_excessive：查询或计算成本过高
ambiguous_feature：特征定义不清
bad_entity_mapping：实体映射错误
```

假设树结构：

```text
H_001 原始假设
  ├── H_001a 加入外债/GDP 交互项
  ├── H_001b 只看高通胀国家
  └── H_001c 改为 14 日窗口
```

---

## 16. 大模型的数学角色

大模型可以做：

```text
提出假设
形式化变量关系
选择候选特征
建议控制变量
解释失败原因
寻找反例
提出修正假设
生成实验报告
```

大模型不可以做：

```text
直接修改生产参数
直接执行任意 SQL
绕过回测
自行把结果判定为 supported
删除失败假设
修改实体映射历史
```

核心原则：

```text
LLM 生成 claim，系统验证 claim。
LLM 不是真理裁判，验证引擎才是裁判。
```

---

## 17. 第一版最小数学范围

MVP 只做：

```text
实体：50–80 个国家
频率：日频
关系：8–12 类
主题：金融压力、通胀、央行、抗议、制裁、战争、能源、债务
模型：指数 + 面板回归 + 离散事件传播
验证：walk-forward + placebo + FDR
LLM：Hypothesis DSL 提交与结果解释
```

核心指标：

```text
domestic_risk_pressure
financial_stress_narrative
policy_hawkishness
policy_uncertainty
social_unrest_pressure
external_conflict_pressure
bilateral_tension
media_attention_shock
```

---

## 18. 参考资料

- GDELT Data 页面： https://www.gdeltproject.org/data.html
- GDELT 2.0 发布说明： https://blog.gdeltproject.org/gdelt-2-0-our-global-world-in-realtime/
- GDELT Events / EventMentions / GKG 联合查询说明： https://blog.gdeltproject.org/complex-queries-combining-events-eventmentions-and-gkg/
- GDELT Event Codebook V2.0： https://data.gdeltproject.org/documentation/GDELT-Event_Codebook-V2.0.pdf
- GDELT DOC 2.0 API： https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/
- GDELT Context 2.0 API： https://blog.gdeltproject.org/announcing-the-gdelt-context-2-0-api/
- GDELT partitioned BigQuery tables： https://blog.gdeltproject.org/announcing-partitioned-gdelt-bigquery-tables/
- ONS GDELT 技术附录： https://www.ons.gov.uk/peoplepopulationandcommunity/birthsdeathsandmarriages/deaths/methodologies/globaldatabaseofeventslanguageandtonegdeltappendix
