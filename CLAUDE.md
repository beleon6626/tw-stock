# CLAUDE.md — 籌碼戰情室

台股三大法人籌碼追蹤平台。靜態網頁部署於 GitHub Pages，Python 腳本每日抓資料寫成 JSON，前端直接 fetch 這些 JSON 顯示。

---

## 架構概覽

```
index.html          唯一前端頁面（Vanilla JS + Tailwind CSS + LightweightCharts + Chart.js）
scripts/            Python 資料抓取腳本（GitHub Actions 每日執行）
*.json              資料檔（由腳本產生，GitHub Actions 自動 push 回 repo）
.github/workflows/  update_data.yml — 每天 22:00 台灣時間自動執行
```

**部署 URL**: `https://beleon6626.github.io/tw-stock/`

---

## 前端 (index.html)

### 全域變數（JS）

| 變數 | 來源 | 說明 |
|------|------|------|
| `DATA` | `data.json` | 全市場法人買賣超。29,000+ 股票，結構：`{stockId: {name, sector, records[]}}` |
| `KLINE` | 空物件（不再預載） | K 線快取，動態抓取後存入 `KLINE[stockId]` |
| `INSIGHTS` | `insights.json` | 排行榜：外資比例、爆量等 |
| `MKT_KLINE` | `index_kline.json` | 加權指數日線 |
| `MKT_FUT` | `futures_kline.json` | 外資期貨未平倉 |
| `MKT_FUND` | `fund_kline.json` | 外資現貨買賣超 |
| `MKT_RETAIL` | `mxf_retail.json` | 散戶多空比（小台指） |
| `MKT_MARGIN` | `margin_ratio.json` | 融資餘額（億元），結構：`{TWSE: [{date, ratio}]}` |
| `INDUSTRY` | `industry_tags.json` | 49 支追蹤股票的 `{name, sector, exchange}`，決定 `.TW` 或 `.TWO` |
| `STOCKS` | 由 `DATA` + `INDUSTRY` 合併 | 自動完成用，包含全市場 29,000+ 支 |

### K 線取得流程

```
loadStock(id)
  → renderStockCharts(id)  [async]
    → 若 KLINE[id] 已有快取 → 直接畫圖
    → 否則 → 顯示 loading spinner
              → fetchKlineDynamic(id)
                  使用 corsproxy.io 代理 Yahoo Finance API
                  URL: https://corsproxy.io/?{encodeURIComponent(yahooUrl)}
                  依 INDUSTRY[id].exchange 決定先試 .TW 或 .TWO
              → 成功 → 存入 KLINE[id]，補更新股價顯示，繪圖
              → 失敗 → 顯示錯誤訊息
```

**重要**：Yahoo Finance API 的 `query2.finance.yahoo.com` 在 GitHub Pages 環境下 CORS 被封鎖，必須透過 `corsproxy.io` 中繼。時間戳記需 +28800 秒轉台灣時區，再用 `.getUTC*()` 取正確日期。

### 主要函式

| 函式 | 說明 |
|------|------|
| `loadAllData()` | 頁面初始化，依序 fetch 所有 JSON |
| `loadStock(id)` | 切換到個股查詢，顯示法人統計 |
| `async renderStockCharts(id)` | 畫 K 線 + KD + 法人買賣超圖 |
| `fetchKlineDynamic(stockId)` | 透過 corsproxy 從 Yahoo Finance 抓 6 個月日線 |
| `renderInsights()` | 渲染觀察清單排行榜 |
| `initMarketCharts()` | 渲染大盤 5 張圖表 |
| `renderETF()` | 渲染 ETF 持股 |
| `calcMA(data, n)` | 移動平均線 |
| `calcKD(data, n=9)` | KD 指標（隨機指標） |
| `aggKline(data, period)` | 日線聚合成週/月 K |

### 四個 Tab

- **觀察清單**：外資/投信買超賣超排行（1/5/10日切換）、新進榜、爆量股
- **個股查詢**：搜尋任意股票、K線+KD+法人圖表+明細表
- **大盤K線**：加權指數、外資期貨未平倉、外資現貨、散戶多空比、融資餘額
- **ETF追蹤**：持股比重、變化量、NEW/OUT 標記（FinMind API，目前部分功能失效）

---

## Python 腳本

### 執行方式

```bash
python scripts/run_all.py           # 一般更新（近 5 個交易日）
python scripts/run_all.py --init    # 初始化回填（近 30 個交易日）
```

### 執行順序（run_all.py）

1. `fetch_institutional.py` → `data.json`（TWSE T86 API，全市場法人買賣超）
2. `fetch_kline.py` → `Kline.json`（**已廢棄前端使用**，但 Actions 仍執行）
3. `fetch_market.py` → 5 個 JSON（大盤資料）
4. `fetch_vix.py` → `vix.json`
5. `fetch_etf.py` → `etf_*.json`（FinMind API，常有 422 錯誤）
6. `build_insights.py` → `insights.json` / `newcomers.json` / `explosive.json`

### 各腳本說明

| 腳本 | 輸出 | 資料來源 | 備註 |
|------|------|------|------|
| `fetch_institutional.py` | `data.json` | TWSE T86 API | 全市場 29,000+ 筆，每日一次 |
| `fetch_kline.py` | `Kline.json` | yfinance | 前端已改為動態抓取，此檔案可廢棄 |
| `fetch_market.py` | 5 個 JSON | TWSE / TAIFEX | 見下方 |
| `fetch_vix.py` | `vix.json` | Yahoo Finance | VIX + VIXTWN |
| `fetch_etf.py` | `etf_*.json` | FinMind API | 需 FINMIND_TOKEN secret |
| `build_insights.py` | `insights.json` 等 | 計算自 data.json | 排行榜邏輯 |

### fetch_market.py 輸出對應

| 函式 | 輸出檔 | API | 備註 |
|------|-------|------|------|
| `fetch_taiex_kline()` | `index_kline.json` | TWSE | 加權指數日線 |
| `fetch_futures_oi()` | `futures_kline.json` | TAIFEX | 外資期貨淨未平倉 |
| `compute_foreign_spot()` | `fund_kline.json` | 計算自 data.json | 外資現貨買賣超 |
| `fetch_retail_ratio()` | `mxf_retail.json` | TAIFEX OpenAPI | 散戶小台多空比，只能逐日累積 |
| `fetch_margin_ratio()` | `margin_ratio.json` | TWSE MI_MARGN | 融資餘額（億元），支援 `days_back` 回填 |

### config.py 關鍵設定

- `STOCK_LIST`：49 支追蹤股票（K 線預熱 + insights 排行）
- `ETF_LIST`：6 支 ETF
- `HISTORY_DAYS = 90`：JSON 保留天數
- `TWSE_DELAY = 0.8`、`TAIFEX_DELAY = 1.0`：請求間隔（秒）

---

## 資料流程圖

```
GitHub Actions (每日 22:00 台灣時間)
  → Python scripts → 寫入 *.json → git push 回 repo
  → GitHub Pages 自動更新靜態檔案

使用者瀏覽器
  → fetch *.json (法人/大盤/排行榜)
  → 個股 K 線：corsproxy.io → Yahoo Finance (即時)
```

---

## 已知問題 / 注意事項

1. **data.json 過大（~31MB）**：頁面初始化需等待此檔案下載完才能繼續，在慢速網路下會較慢。

2. **TWSE MI_MARGN API 格式**：舊版用 `j.data`，現版用 `j.tables[0].data`。腳本已更新為相容兩種格式。融資維持率欄位已消失，改抓「融資金額(仟元)今日餘額」換算為億元。

3. **散戶多空比歷史資料少**：TAIFEX API 只回傳最新一天，無法回填，需每日累積。

4. **ETF Tab**：FinMind 已移除 `TaiwanETFStockDetail` dataset（422 錯誤），ETF 成分股功能目前半廢。

5. **Kline.json**：前端已不再預載，但 `fetch_kline.py` 仍在 Actions 中執行（可日後移除）。

6. **corsproxy.io**：免費公用服務，有機率不穩定。若 K 線動態抓取失敗，可考慮換備用 proxy。

7. **本機 SSL 問題**：Windows 環境執行 `fetch_market.py` 時，`www.twse.com.tw` 可能出現 SSL 憑證驗證錯誤（`Missing Subject Key Identifier`），但 GitHub Actions（Ubuntu）環境正常。

---

## GitHub Actions

- 設定檔：`.github/workflows/update_data.yml`
- 排程：每週一到五 UTC 14:00（台灣時間 22:00）
- 手動觸發：Actions 頁 → 選 `init`（回填 30 天）或 `update`（近 5 天）
- 需要 Secrets：`FINMIND_TOKEN`（選填，ETF 功能用）

---

## git 操作注意

Actions 每天自動 commit JSON 資料，本地 push 前需先 rebase：

```bash
git pull --rebase origin main && git push
```
