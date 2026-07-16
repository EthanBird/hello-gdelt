# Data contract rules

## Required lineage

每个数据文件和控制面记录至少包含：

- dataset name and layer；
- source URL/file identity and batch；
- source byte size and checksum；
- row count and field-count validation；
- schema version；
- mapping/config/code version；
- UTC creation/observation time；
- parent artifact or source-file identifier。

## Compatibility

- 新增 nullable 字段：minor schema change；
- 删除、重命名、改类型、改主键或语义：major schema change；
- 映射规则变化不覆盖旧版本，必须提高 `mapping_version`；
- 不兼容变更必须给出重建范围和迁移/回滚方法。

## Layer rules

- Bronze 忠实保存源字段和摄取元数据，不做不可逆语义修正；
- Silver 执行类型化、去重、实体/关系映射和坏记录隔离；
- Gold 只从版本明确的 Silver 生成，粒度、分母、窗口和单位必须固定；
- runtime `data/` 永不提交 Git。

## Current M1 contracts

| Dataset | Grain | Schema |
|---|---|---|
| Bronze `gdelt_events` | one raw event row | GDELT Events 61 fields + source metadata |
| Silver `world_event` | one deduplicated event observation | `world_event_v1` |
| Gold `country_day_state` | event date × action country | `gold_country_day_state_v1` |
| Gold `pair_day_relation` | event date × actor1 country × actor2 country × relation class | `gold_pair_day_relation_v1` |
