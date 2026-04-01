# 籌碼戰情室 — Taiwan Stock Chip Analysis

台股三大法人籌碼追蹤平台，靜態部署於 GitHub Pages，資料每日自動更新。

## 功能

| Tab | 說明 |
|-----|------|
| 觀察清單 | 外資/投信 買超/賣超排行（1日/5日/10日），新進榜，爆量股 |
| 個股查詢 | K線圖 + MA + KD指標 + 法人買賣超圖表 + 明細表 |
| 大盤K線 | 加權指數 + 外資期貨未平倉 + 現貨買賣超 + 散戶多空比 + 融資維持率 |
| ETF追蹤 | 持股比重、變化量、NEW/OUT 標記、全市場反查 |

## 技術架構

```
前端：Vanilla JS + Tailwind CSS + LightweightCharts + Chart.js（GitHub Pages）
後端：Python 腳本 + GitHub Actions 每日自動抓資料 → 寫入 JSON → push 回 repo
```

## 資料來源

| 資料 | 來源 |
|------|------|
| 三大法人買賣超 | TWSE 開放資料 (T86 API) |
| 個股/大盤 K線 | Yahoo Finance (yfinance) |
| VIX / VIXTWN | Yahoo Finance |
| 期貨未平倉 | TAIFEX 台灣期貨交易所 |
| 融資維持率 | TWSE 開放資料 |
| ETF 成分股 | FinMind API |

## 快速開始

### 1. 安裝 Python 套件

```bash
pip install -r scripts/requirements.txt
```

### 2. 初始化資料（第一次執行）

```bash
python scripts/run_all.py --init
```

### 3. 之後每日更新

```bash
python scripts/run_all.py
```

### 4. 本地預覽

```bash
# 需要本地 HTTP server（不能直接開 file://，fetch 會被 CORS 擋）
python -m http.server 8080
# 瀏覽器打開 http://localhost:8080
```

## 部署到 GitHub Pages

1. 建立 GitHub Repo，把整個資料夾 push 上去
2. `Settings → Pages → Source: main branch, folder: / (root)`
3. 到 `Actions` 頁面，手動觸發 workflow（選 `init` 模式）跑第一次
4. 之後每天台灣時間 22:00 自動執行

### FinMind Token（選填）

免費版有每日請求限額。如需完整 ETF 資料：
1. 至 https://finmindtrade.com/ 申請帳號
2. Repo → `Settings → Secrets → New secret`
3. Name: `FINMIND_TOKEN`，Value: 你的 token

## 專案結構

```
├── index.html                    # 前端主頁
├── scripts/
│   ├── config.py                 # 股票清單、ETF 清單、設定
│   ├── requirements.txt          # Python 套件
│   ├── run_all.py                # 主執行腳本
│   ├── fetch_institutional.py    # 法人買賣超 (TWSE)
│   ├── fetch_kline.py            # K線資料 (yfinance)
│   ├── fetch_market.py           # 大盤資料
│   ├── fetch_vix.py              # VIX (Yahoo Finance)
│   ├── fetch_etf.py              # ETF 成分股 (FinMind)
│   └── build_insights.py         # 排行榜計算
├── .github/workflows/
│   └── update_data.yml           # GitHub Actions 排程
└── *.json                        # 自動產生的資料檔
```
