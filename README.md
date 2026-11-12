# 01-feedstitch（信汇）

Feedstitch — 多源目录/价目 Feed 归并落库：解析 → 业务键去重/冲突隔离 → 按源水位线增量或全量落库。

## 启动

```bash
docker compose up --build
```

| 入口 | 地址 |
| --- | --- |
| 前端 | http://localhost:5100 |
| API | http://localhost:10100 |

## 主链

配置源与夹具 → 触发 Run → 解析 / 去重 / 冲突隔离 → Canonical + 运行报告对账

## 种子说明

- **Alpha Catalog（clean）**：JSON，三件干净货号，增量可落库。
- **Beta Offers（dirty）**：JSONL，含与 Alpha 同键但价格不同的冲突行，以及迟到低 revision 行（底座增量会因水位线跳过）。
- **Gamma Shelf（xml）**：简易 XML，两件独立货号。

打开“运行台”选源跑一次增量，再看 Staging / 冲突 / Canonical 三页计数是否与本次 Run 报告一致。

## 目录巡检采集

「目录采集」页（`/harvest`）可指定本机目录（留空 = 仓库内 `backend/app/fixtures`），
递归扫描 `.json` / `.jsonl` / `.xml` 夹具，生成采集任务与文件清单，并把每个采集成功的
文件作为临时源交给既有摄取链路。业务键去重、同键非键冲突隔离和 Canonical 保护规则不变。

任务报告与摄取报告共用同一批 Run / Staging / Conflicts / Canonical 数据：

- 发现文件数 = 成功采集数 + 采集失败数
- 解析条目数 = 摄取 parsed
- Staging 行数 = 摄取 parsed（每行带 disposition）
- 冲突行数 = 摄取 conflict，且 Canonical 不被同键异值静默覆盖
- Canonical Δ = insert 数

```bash
curl -X POST localhost:10100/api/harvests \
  -H 'Content-Type: application/json' \
  -d '{"directory":"fixtures","recursive":true,"ingest":true,"mode":"incremental"}'
```

`ingest=false` 只扫描生成清单；之后 `POST /api/harvests/{id}/ingest` 可补触发摄取。

## 技术栈

Python 3.12 + FastAPI + SQLite；Vue 3 + Vite + Nginx。

## 0-1 切口（未实现）

`lookback_backfill` / `schema_drift_guard` / `dead_letter_replay` / `webhook_push_source` /
`source_authority_rank` / `tombstone_retire` / `scd2_history` / `watermark_commit_gate` /
`field_map_transform` / `lineage_provenance` /
`bronze_silver_promote` / `category_metric_mart` / `pii_mask_export` /
`rpa_form_queue`
