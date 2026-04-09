"""
fetch_daily_prices.py
─────────────────────
從 TWSE / TPEX 抓取全市場當日收盤價與成交量，
回填 data.json 中每支股票最新一筆 records 的 close / volume 欄位。

資料來源：
  TWSE：https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY_ALL
  TPEX：https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes

執行時機：在 fetch_institutional.py 之後、build_insights.py 之前執行。
"""

import json
import os
import sys
import time
import warnings
import requests
from datetime import datetime

warnings.filterwarnings("ignore")

sys.path.insert(0, os.path.dirname(__file__))
from config import OUT_DIR, HEADERS, TWSE_DELAY

DATA_FILE = os.path.join(OUT_DIR, "data.json")

TWSE_URL = "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY_ALL"
TPEX_URL = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"


def parse_price(s) -> float:
    try:
        return float(str(s).replace(",", ""))
    except (ValueError, TypeError):
        return 0.0


def parse_volume(s) -> int:
    """成交股數（股）→ 張（1張=1000股）"""
    try:
        return int(str(s).replace(",", "")) // 1000
    except (ValueError, TypeError):
        return 0


def fetch_twse_prices() -> dict:
    """回傳 {stock_id: {close, volume}}，涵蓋所有上市股票。"""
    try:
        r = requests.get(TWSE_URL, params={"response": "json"},
                         headers=HEADERS, timeout=20, verify=False)
        r.raise_for_status()
        j = r.json()
        if j.get("stat") != "OK" or not j.get("data"):
            print("  TWSE STOCK_DAY_ALL：無資料")
            return {}

        result = {}
        for row in j["data"]:
            sid = str(row[0]).strip()
            if not sid.isdigit():
                continue
            result[sid] = {
                "close":  parse_price(row[7]),   # 收盤價
                "volume": parse_volume(row[2]),  # 成交股數→張
            }
        print(f"  TWSE：{len(result)} 支股票收盤價/成交量")
        return result
    except Exception as e:
        print(f"  TWSE STOCK_DAY_ALL 錯誤：{e}")
        return {}


def fetch_tpex_prices() -> dict:
    """回傳 {stock_id: {close, volume}}，涵蓋所有上櫃股票。"""
    try:
        r = requests.get(TPEX_URL, headers=HEADERS, timeout=20, verify=False)
        r.raise_for_status()
        j = r.json()
        if not isinstance(j, list):
            print("  TPEX mainboard_daily_close_quotes：無資料")
            return {}

        result = {}
        for row in j:
            sid = str(row.get("SecuritiesCompanyCode", "")).strip()
            if not sid.isdigit():
                continue
            result[sid] = {
                "close":  parse_price(row.get("Close", 0)),
                "volume": parse_volume(row.get("TradingShares", 0)),
            }
        print(f"  TPEX：{len(result)} 支股票收盤價/成交量")
        return result
    except Exception as e:
        print(f"  TPEX mainboard_daily_close_quotes 錯誤：{e}")
        return {}


def update_prices(days_back: int = 1):
    """
    抓取今日收盤價與成交量，更新 data.json 中最新一筆記錄的 close / volume。
    只更新日期符合今日（或最近交易日）的記錄。
    """
    print("[fetch_daily_prices] 開始更新全市場收盤價/成交量...")

    if not os.path.exists(DATA_FILE):
        print("  data.json 不存在，請先執行 fetch_institutional.py")
        return

    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data: dict = json.load(f)

    # 抓今日價格
    twse_prices = fetch_twse_prices()
    time.sleep(TWSE_DELAY)
    tpex_prices = fetch_tpex_prices()

    all_prices = {**twse_prices, **tpex_prices}

    if not all_prices:
        print("  無法取得任何價格資料，跳過")
        return

    updated = 0
    for sid, info in data.items():
        if sid not in all_prices:
            continue
        records = info.get("records", [])
        if not records:
            continue
        # 只更新最新一筆（今日）
        last = records[-1]
        p = all_prices[sid]
        if p["close"] > 0:
            last["close"] = p["close"]
        if p["volume"] > 0:
            last["volume"] = p["volume"]
            updated += 1

    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))

    print(f"[fetch_daily_prices] 完成：更新 {updated} 支股票的收盤價/成交量")


if __name__ == "__main__":
    update_prices()
