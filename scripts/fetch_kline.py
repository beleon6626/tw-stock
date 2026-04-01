"""
fetch_kline.py
──────────────
用 yfinance 抓取個股 OHLCV K 線資料，寫入 Kline.json。
同時把收盤價／成交量回填到 data.json 裡（fetch_institutional 先跑完再跑這支）。

Yahoo Finance 台股代號規則：
  上市股票：{代號}.TW   例：2330.TW
  上櫃股票：{代號}.TWO  例：6547.TWO
"""

import json
import os
import sys
import time

import yfinance as yf
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
from config import OUT_DIR, STOCK_LIST, HISTORY_DAYS

KLINE_FILE = os.path.join(OUT_DIR, "Kline.json")
DATA_FILE  = os.path.join(OUT_DIR, "data.json")

# yfinance 一次批次抓取的股數（太多容易被限速）
BATCH_SIZE = 10
BATCH_DELAY = 2.0   # 秒


# ── 工具 ──────────────────────────────────────────────────────────────────

def fetch_one_stock(stock_id: str, exchange: str, period: str = "4mo") -> list | None:
    """
    抓取單支股票的 OHLCV，回傳 list of dict（LightweightCharts 格式）。
    period: yfinance 週期字串，例如 '4mo', '1y'
    """
    ticker_sym = f"{stock_id}.{exchange}"
    try:
        tk = yf.Ticker(ticker_sym)
        df = tk.history(period=period, auto_adjust=True)

        if df.empty:
            print(f"    {ticker_sym}: 無資料")
            return None

        # 統一時區 → 日期字串
        df.index = pd.to_datetime(df.index).tz_localize(None).strftime("%Y-%m-%d")
        df = df[["Open", "High", "Low", "Close", "Volume"]].copy()

        records = []
        for date_str, row in df.iterrows():
            vol_lots = int(row["Volume"] // 1000) if row["Volume"] > 0 else 0
            records.append({
                "time":   date_str,
                "open":   round(float(row["Open"]),  2),
                "high":   round(float(row["High"]),  2),
                "low":    round(float(row["Low"]),   2),
                "close":  round(float(row["Close"]), 2),
                "volume": vol_lots,
            })

        # 保留最近 N 天
        return records[-HISTORY_DAYS:]

    except Exception as e:
        print(f"    {ticker_sym} 錯誤: {e}")
        return None


# ── 主流程 ────────────────────────────────────────────────────────────────

def update_klines():
    print("[fetch_kline] 開始抓取個股 K 線...")

    # 載入現有資料
    kline_data: dict = {}
    if os.path.exists(KLINE_FILE):
        with open(KLINE_FILE, "r", encoding="utf-8") as f:
            kline_data = json.load(f)

    inst_data: dict = {}
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            inst_data = json.load(f)

    updated = 0

    for i, (stock_id, name, sector, exchange) in enumerate(STOCK_LIST):
        print(f"  [{i+1}/{len(STOCK_LIST)}] {stock_id} {name}...", end=" ")

        records = fetch_one_stock(stock_id, exchange)

        if records:
            kline_data[stock_id] = records
            updated += 1

            # 回填 close / volume 到 data.json
            if stock_id in inst_data:
                price_map = {r["time"]: (r["close"], r["volume"]) for r in records}
                for rec in inst_data[stock_id]["records"]:
                    d = rec["date"]
                    if d in price_map:
                        rec["close"]  = price_map[d][0]
                        rec["volume"] = price_map[d][1]
            print("OK")
        else:
            print("跳過")

        # 每 BATCH_SIZE 支暫停一下避免被限速
        if (i + 1) % BATCH_SIZE == 0:
            print(f"  (批次暫停 {BATCH_DELAY}s...)")
            time.sleep(BATCH_DELAY)

    # 寫回 Kline.json
    with open(KLINE_FILE, "w", encoding="utf-8") as f:
        json.dump(kline_data, f, ensure_ascii=False, separators=(",", ":"))

    # 寫回 data.json（已填入 close/volume）
    if inst_data:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(inst_data, f, ensure_ascii=False, separators=(",", ":"))

    print(f"[fetch_kline] 完成：共更新 {updated} 支股票 K 線")


if __name__ == "__main__":
    update_klines()
