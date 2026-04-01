"""
fetch_market.py
───────────────
抓取大盤總覽所需的五組資料：

  1. index_kline.json    加權指數 K 線          → yfinance ^TWII
  2. futures_kline.json  外資期貨淨未平倉（口）  → TAIFEX Open API
  3. fund_kline.json     外資現貨買賣超（億元）  → 由 data.json 加總
  4. mxf_retail.json     散戶多空比（%）         → TAIFEX Open API
  5. margin_ratio.json   融資維持率（%）         → TWSE Open API
"""

import json
import os
import sys
import time
import requests

import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(__file__))
from config import OUT_DIR, HEADERS, TWSE_DELAY, TAIFEX_DELAY, HISTORY_DAYS

INDEX_KLINE_FILE = os.path.join(OUT_DIR, "index_kline.json")
FUTURES_FILE     = os.path.join(OUT_DIR, "futures_kline.json")
FUND_FILE        = os.path.join(OUT_DIR, "fund_kline.json")
RETAIL_FILE      = os.path.join(OUT_DIR, "mxf_retail.json")
MARGIN_FILE      = os.path.join(OUT_DIR, "margin_ratio.json")
DATA_FILE        = os.path.join(OUT_DIR, "data.json")

TODAY = datetime.now().strftime("%Y-%m-%d")


# ────────────────────────────────────────────────────────────────────────────
# 共用小工具
# ────────────────────────────────────────────────────────────────────────────

def load_json_list(path: str) -> list:
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def load_json_dict(path: str) -> dict:
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def merge_and_save(existing: list, new_records: list, key: str, path: str):
    """合併新舊資料（以 key 欄位去重），保留最近 HISTORY_DAYS 筆，寫檔。"""
    merged = {r[key]: r for r in existing}
    for r in new_records:
        merged[r[key]] = r
    out = sorted(merged.values(), key=lambda x: x[key])[-HISTORY_DAYS:]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    return out


def get_recent_trading_dates(n: int = 5) -> list[str]:
    """取最近 n 個週一到週五，格式 YYYYMMDD，由新到舊。"""
    dates, d = [], datetime.now()
    while len(dates) < n:
        if d.weekday() < 5:
            dates.append(d.strftime("%Y%m%d"))
        d -= timedelta(days=1)
    return dates


# ────────────────────────────────────────────────────────────────────────────
# 1. 加權指數 K 線
# ────────────────────────────────────────────────────────────────────────────

def fetch_taiex_kline():
    print("  [1/5] 加權指數 K 線...")
    try:
        tk = yf.Ticker("^TWII")
        df = tk.history(period="4mo", auto_adjust=True)

        if df.empty:
            print("    ^TWII 無資料")
            return

        df.index = pd.to_datetime(df.index).tz_localize(None).strftime("%Y-%m-%d")
        new_records = []
        for date_str, row in df.iterrows():
            new_records.append({
                "time":  date_str,
                "open":  round(float(row["Open"]),  0),
                "high":  round(float(row["High"]),  0),
                "low":   round(float(row["Low"]),   0),
                "close": round(float(row["Close"]), 0),
            })

        existing = load_json_list(INDEX_KLINE_FILE)
        out = merge_and_save(existing, new_records, "time", INDEX_KLINE_FILE)
        print(f"    加權指數：已儲存 {len(out)} 筆")

    except Exception as e:
        print(f"    加權指數錯誤: {e}")


# ────────────────────────────────────────────────────────────────────────────
# 2. 外資期貨淨未平倉 → TAIFEX Open API (JSON)
#
# API: https://openapi.taifex.com.tw/v1/FuturesAndOptionsContractPositionOfDealerAndInstitutions
# 回傳陣列，每筆包含：
#   Date, ContractCode, ContractName, IdentityCode, IdentityName,
#   LongOpenInterest, ShortOpenInterest, NetOpenInterest
# 我們要：ContractCode="TXF"（台指期大台）, IdentityName 包含 "外資"
# ────────────────────────────────────────────────────────────────────────────

def fetch_futures_oi():
    """使用 TAIFEX Open API 抓外資台指期淨未平倉（口數）。"""
    print("  [2/5] 外資期貨淨未平倉...")

    url = "https://openapi.taifex.com.tw/v1/FuturesAndOptionsContractPositionOfDealerAndInstitutions"
    headers = {**HEADERS, "Accept": "application/json"}

    try:
        resp = requests.get(url, headers=headers, timeout=20)
        resp.raise_for_status()
        data = resp.json()

        if not isinstance(data, list) or not data:
            print("    TAIFEX Open API 無資料")
            return

        # 找台指期 + 外資的最新日期資料
        # ContractCode: "TXF" = 台指期大台
        txf_rows = [
            r for r in data
            if str(r.get("ContractCode", "")).strip() == "TXF"
            and "外資" in str(r.get("IdentityName", ""))
        ]

        if not txf_rows:
            # 備用：找所有含「臺股」的
            txf_rows = [
                r for r in data
                if "臺股" in str(r.get("ContractName", ""))
                and "外資" in str(r.get("IdentityName", ""))
            ]

        if not txf_rows:
            print("    找不到台指期外資資料")
            return

        # 取最新日期
        latest = sorted(txf_rows, key=lambda r: r.get("Date", ""), reverse=True)[0]
        net_oi = int(str(latest.get("NetOpenInterest", "0")).replace(",", ""))
        date_raw = str(latest.get("Date", TODAY))
        # 日期格式可能是 YYYY/MM/DD 或 YYYYMMDD
        if "/" in date_raw:
            date_fmt = date_raw.replace("/", "-")
        elif len(date_raw) == 8:
            date_fmt = f"{date_raw[:4]}-{date_raw[4:6]}-{date_raw[6:]}"
        else:
            date_fmt = TODAY

        color = "#ef4444" if net_oi >= 0 else "#22c55e"
        existing = load_json_list(FUTURES_FILE)
        out = merge_and_save(existing,
                             [{"time": date_fmt, "value": net_oi, "color": color}],
                             "time", FUTURES_FILE)
        print(f"    外資期貨淨未平倉: {net_oi:+,d} 口（{date_fmt}），共 {len(out)} 筆歷史")

    except Exception as e:
        print(f"    外資期貨 OI 錯誤: {e}")

    time.sleep(TAIFEX_DELAY)


# ────────────────────────────────────────────────────────────────────────────
# 3. 外資現貨買賣超（由 data.json 加總）
# ────────────────────────────────────────────────────────────────────────────

def compute_foreign_spot():
    print("  [3/5] 外資現貨買賣超（計算中）...")
    if not os.path.exists(DATA_FILE):
        print("    data.json 不存在，跳過")
        return

    data = load_json_dict(DATA_FILE)
    daily: dict[str, int] = {}
    for sid, info in data.items():
        for rec in info.get("records", []):
            d = rec["date"]
            daily[d] = daily.get(d, 0) + rec.get("foreign", 0)

    new_records = []
    for d, total_lots in sorted(daily.items()):
        billion = round(total_lots / 1000, 1)
        color   = "#ef4444" if billion >= 0 else "#22c55e"
        new_records.append({"time": d, "value": billion, "color": color})

    existing = load_json_list(FUND_FILE)
    out = merge_and_save(existing, new_records, "time", FUND_FILE)
    print(f"    外資現貨：已儲存 {len(out)} 筆")


# ────────────────────────────────────────────────────────────────────────────
# 4. 散戶多空比 → TAIFEX Open API
#
# API: https://openapi.taifex.com.tw/v1/FuturesAndOptionsContractPositionOfRetailerAndInstitutions
# 欄位：Date, ContractCode, IdentityCode, IdentityName,
#        LongOpenInterest, ShortOpenInterest, NetOpenInterest
# 散戶 = IdentityName 包含 "散戶" 或 "一般"，ContractCode = "MTX"（小台）
# 多空比 = Long / (Long + Short) * 100
# ────────────────────────────────────────────────────────────────────────────

def fetch_retail_ratio():
    """使用 TAIFEX Open API 抓散戶小台指多空比。"""
    print("  [4/5] 散戶多空比...")

    url = "https://openapi.taifex.com.tw/v1/FuturesAndOptionsContractPositionOfRetailerAndInstitutions"
    headers = {**HEADERS, "Accept": "application/json"}

    try:
        resp = requests.get(url, headers=headers, timeout=20)
        resp.raise_for_status()
        data = resp.json()

        if not isinstance(data, list) or not data:
            print("    TAIFEX Retail API 無資料")
            return

        # 找小台指（MTX）的散戶資料
        retail_rows = [
            r for r in data
            if str(r.get("ContractCode", "")).strip() == "MTX"
            and any(kw in str(r.get("IdentityName", "")) for kw in ["散戶", "一般", "Retail"])
        ]

        if not retail_rows:
            # 備用：找所有非法人（外資/投信/自營）的小台資料
            inst_names = {"外資", "投信", "自營商", "Dealer"}
            retail_rows = [
                r for r in data
                if str(r.get("ContractCode", "")).strip() == "MTX"
                and not any(kw in str(r.get("IdentityName", "")) for kw in inst_names)
            ]

        if not retail_rows:
            print("    找不到散戶小台資料，嘗試用整體計算...")
            # 再備用：從全市場減法人
            _compute_retail_from_total(data)
            return

        latest = sorted(retail_rows, key=lambda r: r.get("Date", ""), reverse=True)[0]
        long_oi  = int(str(latest.get("LongOpenInterest",  "0")).replace(",", ""))
        short_oi = int(str(latest.get("ShortOpenInterest", "0")).replace(",", ""))
        net_oi   = int(str(latest.get("NetOpenInterest",   "0")).replace(",", ""))
        total    = long_oi + short_oi
        ratio    = round(long_oi / total * 100, 2) if total > 0 else 0.0

        date_raw = str(latest.get("Date", TODAY))
        if "/" in date_raw:
            date_fmt = date_raw.replace("/", "-")
        elif len(date_raw) == 8:
            date_fmt = f"{date_raw[:4]}-{date_raw[4:6]}-{date_raw[6:]}"
        else:
            date_fmt = TODAY

        existing_data = load_json_dict(RETAIL_FILE) or {"mxf_retail": []}
        existing_list = existing_data.get("mxf_retail", [])
        merged_map    = {r["date"]: r for r in existing_list}
        merged_map[date_fmt] = {
            "date":            date_fmt,
            "retail_net_oi":   net_oi,
            "market_total_oi": total,
            "retail_ratio":    ratio,
        }
        out = sorted(merged_map.values(), key=lambda x: x["date"])[-HISTORY_DAYS:]
        with open(RETAIL_FILE, "w", encoding="utf-8") as f:
            json.dump({"mxf_retail": out}, f, ensure_ascii=False, separators=(",", ":"))

        print(f"    散戶多空比: {ratio}%（多{long_oi:,d} 空{short_oi:,d}，{date_fmt}）")

    except Exception as e:
        print(f"    散戶多空比錯誤: {e}")

    time.sleep(TAIFEX_DELAY)


def _compute_retail_from_total(data: list):
    """備用：從全市場減法人來估算散戶。"""
    mtx_rows = [r for r in data if str(r.get("ContractCode", "")).strip() == "MTX"]
    if not mtx_rows:
        return

    latest_date = sorted(set(r.get("Date", "") for r in mtx_rows), reverse=True)[0]
    day_rows    = [r for r in mtx_rows if r.get("Date") == latest_date]

    total_long = total_short = 0
    inst_long  = inst_short  = 0
    inst_kw    = {"外資", "投信", "自營商"}

    for r in day_rows:
        lo = int(str(r.get("LongOpenInterest",  "0")).replace(",", ""))
        so = int(str(r.get("ShortOpenInterest", "0")).replace(",", ""))
        if "合計" in str(r.get("IdentityName", "")) or "Total" in str(r.get("IdentityName", "")):
            total_long, total_short = lo, so
        elif any(kw in str(r.get("IdentityName", "")) for kw in inst_kw):
            inst_long  += lo
            inst_short += so

    if total_long + total_short == 0:
        return

    ret_long  = max(0, total_long  - inst_long)
    ret_short = max(0, total_short - inst_short)
    total     = ret_long + ret_short
    ratio     = round(ret_long / total * 100, 2) if total > 0 else 0.0

    date_raw = str(latest_date)
    if "/" in date_raw:
        date_fmt = date_raw.replace("/", "-")
    elif len(date_raw) == 8:
        date_fmt = f"{date_raw[:4]}-{date_raw[4:6]}-{date_raw[6:]}"
    else:
        date_fmt = TODAY

    existing_data = load_json_dict(RETAIL_FILE) or {"mxf_retail": []}
    existing_list = existing_data.get("mxf_retail", [])
    merged_map    = {r["date"]: r for r in existing_list}
    merged_map[date_fmt] = {
        "date":            date_fmt,
        "retail_net_oi":   ret_long - ret_short,
        "market_total_oi": total,
        "retail_ratio":    ratio,
    }
    out = sorted(merged_map.values(), key=lambda x: x["date"])[-HISTORY_DAYS:]
    with open(RETAIL_FILE, "w", encoding="utf-8") as f:
        json.dump({"mxf_retail": out}, f, ensure_ascii=False, separators=(",", ":"))
    print(f"    散戶多空比（估算）: {ratio}%（{date_fmt}）")


# ────────────────────────────────────────────────────────────────────────────
# 5. 融資維持率 → TWSE rwd API
#
# 正確 endpoint（rwd 版本）：
#   https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN
#   ?date=YYYYMMDD&selectType=MS&response=json
# 欄位陣列 fields 第 0 欄是「股票名稱」，第 11 欄是「整戶維持率」
# 合計列名稱：「加權平均整戶維持率」或最後一列
# ────────────────────────────────────────────────────────────────────────────

def fetch_margin_ratio():
    print("  [5/5] 融資維持率...")

    twse_ratio = None

    # 嘗試最近幾個交易日（今天可能還沒收盤資料）
    for date_str in get_recent_trading_dates(3):
        url    = "https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN"
        params = {"date": date_str, "selectType": "MS", "response": "json"}
        try:
            resp = requests.get(url, params=params, headers=HEADERS, timeout=20)
            resp.raise_for_status()
            j = resp.json()

            if j.get("stat") != "OK" or not j.get("data"):
                time.sleep(TWSE_DELAY)
                continue

            fields = j.get("fields", [])
            # 找「整戶維持率」或「維持率」的欄位索引
            ratio_idx = None
            for i, f in enumerate(fields):
                if "維持率" in str(f):
                    ratio_idx = i
                    break

            # 找合計列（最後一列通常含「加權平均」）
            for row in reversed(j["data"]):
                row_text = " ".join(str(c) for c in row)
                if "加權" in row_text or "平均" in row_text or "合計" in row_text:
                    # 從指定欄或遍歷找合理數值
                    candidates = [row[ratio_idx]] if ratio_idx is not None else row
                    for cell in candidates:
                        try:
                            v = float(str(cell).replace(",", ""))
                            if 100 < v < 500:
                                twse_ratio = v
                                break
                        except (ValueError, TypeError):
                            continue
                    if twse_ratio:
                        break

            if twse_ratio:
                print(f"    TWSE 融資維持率: {twse_ratio}% ({date_str})")
                break

        except Exception as e:
            print(f"    TWSE 融資維持率錯誤 ({date_str}): {e}")

        time.sleep(TWSE_DELAY)

    # 寫入
    existing = load_json_dict(MARGIN_FILE) or {"TWSE": [], "TPEX": []}

    if twse_ratio is not None:
        twse_map = {r["date"]: r for r in existing.get("TWSE", [])}
        twse_map[TODAY] = {"date": TODAY, "ratio": twse_ratio}
        existing["TWSE"] = sorted(twse_map.values(), key=lambda x: x["date"])[-HISTORY_DAYS:]
    else:
        print("    TWSE 融資維持率：無法取得，保留舊值")

    with open(MARGIN_FILE, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, separators=(",", ":"))

    twse_n = len(existing.get("TWSE", []))
    print(f"    融資維持率：TWSE {twse_n} 筆")


# ────────────────────────────────────────────────────────────────────────────
# 主流程
# ────────────────────────────────────────────────────────────────────────────

def update_market():
    print("[fetch_market] 開始抓取大盤資料...")
    fetch_taiex_kline()
    fetch_futures_oi()
    compute_foreign_spot()
    fetch_retail_ratio()
    fetch_margin_ratio()
    print("[fetch_market] 完成")


if __name__ == "__main__":
    update_market()
