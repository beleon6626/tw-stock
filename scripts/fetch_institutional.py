"""
fetch_institutional.py
──────────────────────
從 TWSE T86 API 抓取「三大法人買賣超股數統計」，
寫入 data.json（每支股票的每日外資/投信/自營商買賣超，單位：張）。

TWSE T86 API：
  https://www.twse.com.tw/fund/T86?response=json&date=YYYYMMDD&selectType=ALL

回傳欄位（fields 陣列）：
  [0] 證券代號
  [1] 證券名稱
  [2] 外陸資買進股數
  [3] 外陸資賣出股數
  [4] 外陸資買賣超股數   ← 我們要的
  [5] 投信買進股數
  [6] 投信賣出股數
  [7] 投信買賣超股數     ← 我們要的
  [8] 自營商買賣超股數   ← 我們要的（合計）
  ...
  [15] 三大法人買賣超股數

數字單位是「股」，除以 1000 轉為「張」。
"""

import json
import os
import sys
import time
import requests
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(__file__))
from config import OUT_DIR, HEADERS, TWSE_DELAY, HISTORY_DAYS

DATA_FILE     = os.path.join(OUT_DIR, "data.json")
INDUSTRY_FILE = os.path.join(OUT_DIR, "industry_tags.json")

T86_URL = "https://www.twse.com.tw/fund/T86"


# ── 工具函式 ──────────────────────────────────────────────────────────────

def parse_num(s: str) -> int:
    """把 '1,234,567' 轉成整數，除以 1000 得張數；錯誤回傳 0。"""
    try:
        return int(str(s).replace(",", "")) // 1000
    except (ValueError, AttributeError):
        return 0


def get_last_n_trading_dates(n: int = 10) -> list[str]:
    """
    取得最近 n 個「可能的交易日」（週一到週五），格式 YYYYMMDD。
    假日無資料時 API 會回傳空，程式會自動跳過。
    """
    dates = []
    d = datetime.now()
    while len(dates) < n:
        if d.weekday() < 5:          # 0=Mon … 4=Fri
            dates.append(d.strftime("%Y%m%d"))
        d -= timedelta(days=1)
    return dates  # 由新到舊


# ── 核心抓取 ──────────────────────────────────────────────────────────────

def fetch_t86_one_day(date_str: str) -> dict | None:
    """
    抓取單日 T86 資料。
    回傳 {stock_id: {name, foreign, invest, dealer}} 或 None（假日/無資料）。
    """
    params = {
        "response":   "json",
        "date":       date_str,
        "selectType": "ALL",
    }
    try:
        resp = requests.get(T86_URL, params=params, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        j = resp.json()

        if j.get("stat") != "OK" or not j.get("data"):
            print(f"    T86 {date_str}: 無資料（假日或非交易日）")
            return None

        result = {}
        for row in j["data"]:
            sid  = str(row[0]).strip()
            name = str(row[1]).strip()
            # 過濾掉非股票代碼（純數字 4–6 碼）
            if not sid.isdigit():
                continue
            result[sid] = {
                "name":    name,
                "foreign": parse_num(row[4]),   # 外資買賣超（張）
                "invest":  parse_num(row[7]),   # 投信買賣超（張）
                "dealer":  parse_num(row[8]),   # 自營商買賣超（張）
            }

        print(f"    T86 {date_str}: OK ({len(result)} 支股票)")
        return result

    except requests.exceptions.RequestException as e:
        print(f"    T86 {date_str} 網路錯誤: {e}")
        return None
    except Exception as e:
        print(f"    T86 {date_str} 解析錯誤: {e}")
        return None


# ── 主流程 ────────────────────────────────────────────────────────────────

def load_existing_data() -> dict:
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def load_industry_tags() -> dict:
    if os.path.exists(INDUSTRY_FILE):
        with open(INDUSTRY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def update_data(days_back: int = 5):
    """
    抓取最近 days_back 個交易日的法人資料，合併寫回 data.json。
    每次執行只補抓「尚未存在」的日期，避免重複。
    """
    print("[fetch_institutional] 開始抓取三大法人買賣超...")

    existing = load_existing_data()
    industry = load_industry_tags()

    dates_to_fetch = get_last_n_trading_dates(days_back)

    for date_str in reversed(dates_to_fetch):   # 由舊到新
        print(f"  → 抓取 {date_str}...")
        date_fmt = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"  # YYYY-MM-DD

        # 檢查是否所有已知股票都已有這天的資料（簡單去重）
        already_have = any(
            any(r["date"] == date_fmt for r in info.get("records", []))
            for info in existing.values()
        )
        if already_have:
            print(f"    {date_str}: 已存在，跳過")
            continue

        day_data = fetch_t86_one_day(date_str)
        if not day_data:
            time.sleep(TWSE_DELAY)
            continue

        for sid, vals in day_data.items():
            if sid not in existing:
                # 從 industry_tags 取得產業別
                sector = industry.get(sid, {}).get("sector", "") if industry else ""
                existing[sid] = {
                    "name":    vals["name"],
                    "sector":  sector,
                    "records": [],
                }

            # 避免重複插入同一天
            existing_dates = {r["date"] for r in existing[sid]["records"]}
            if date_fmt not in existing_dates:
                existing[sid]["records"].append({
                    "date":    date_fmt,
                    "foreign": vals["foreign"],
                    "invest":  vals["invest"],
                    "dealer":  vals["dealer"],
                    "close":   0,     # 由 fetch_kline.py 填入
                    "volume":  0,     # 由 fetch_kline.py 填入
                })

            # 保持時間順序 + 限制長度
            existing[sid]["records"].sort(key=lambda x: x["date"])
            existing[sid]["records"] = existing[sid]["records"][-HISTORY_DAYS:]

        time.sleep(TWSE_DELAY)

    # 寫回
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, separators=(",", ":"))

    total_stocks   = len(existing)
    total_records  = sum(len(v["records"]) for v in existing.values())
    print(f"[fetch_institutional] 完成：{total_stocks} 支股票，共 {total_records} 筆記錄")


if __name__ == "__main__":
    # 直接執行時預設抓最近 10 個交易日
    update_data(days_back=10)
