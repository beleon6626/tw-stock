"""
fetch_market.py
───────────────
抓取大盤總覽所需的五組資料：

  1. index_kline.json    加權指數 K 線          → yfinance ^TWII
  2. futures_kline.json  外資期貨淨未平倉（口）  → TAIFEX HTML 爬蟲
  3. fund_kline.json     外資現貨買賣超（億元）  → 由 data.json 加總
  4. mxf_retail.json     散戶多空比（%）         → TAIFEX HTML 爬蟲
  5. margin_ratio.json   融資維持率（%）         → TWSE API
"""

import json
import os
import sys
import time
import re
import requests

import yfinance as yf
import pandas as pd
from bs4 import BeautifulSoup
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
# 2. 外資期貨淨未平倉（TAIFEX）
# ────────────────────────────────────────────────────────────────────────────

def fetch_futures_oi():
    """
    從 TAIFEX「三大法人 - 區分各期貨契約」頁面爬取外資台指期淨未平倉口數。
    https://www.taifex.com.tw/cht/3/futContractsDate
    """
    print("  [2/5] 外資期貨淨未平倉...")
    url = "https://www.taifex.com.tw/cht/3/futContractsDate"
    taifex_headers = {**HEADERS, "Referer": "https://www.taifex.com.tw/"}

    try:
        resp = requests.get(url, headers=taifex_headers, timeout=20)
        resp.encoding = "utf-8"
        soup = BeautifulSoup(resp.text, "lxml")

        net_oi   = 0
        found    = False

        # 找包含「臺股期貨」的表格
        for table in soup.find_all("table"):
            text = table.get_text()
            if "臺股期貨" not in text and "台股期貨" not in text:
                continue

            rows = table.find_all("tr")
            in_tx_section = False

            for row in rows:
                cells = [c.get_text(strip=True) for c in row.find_all(["th", "td"])]
                if not cells:
                    continue

                # 偵測到臺股期貨區段
                row_text = " ".join(cells)
                if "臺股期貨" in row_text or "台股期貨" in row_text:
                    in_tx_section = True

                if not in_tx_section:
                    continue

                # 外資那一列
                if "外資" in cells[0] or (len(cells) > 1 and "外資" in cells[1]):
                    # 多空淨額口數通常在倒數第 3 或第 4 格
                    for cell in reversed(cells):
                        clean = cell.replace(",", "").replace("+", "")
                        if re.match(r"^-?\d+$", clean):
                            net_oi = int(clean)
                            found  = True
                            break
                    if found:
                        break
            if found:
                break

        if not found:
            print("    無法解析外資期貨 OI，保留舊值")
            return

        color = "#ef4444" if net_oi >= 0 else "#22c55e"
        existing = load_json_list(FUTURES_FILE)
        out = merge_and_save(existing,
                             [{"time": TODAY, "value": net_oi, "color": color}],
                             "time", FUTURES_FILE)
        print(f"    外資期貨淨未平倉: {net_oi:+,d} 口，共 {len(out)} 筆歷史")

    except Exception as e:
        print(f"    外資期貨 OI 錯誤: {e}")

    time.sleep(TAIFEX_DELAY)


# ────────────────────────────────────────────────────────────────────────────
# 3. 外資現貨買賣超（由 data.json 加總）
# ────────────────────────────────────────────────────────────────────────────

def compute_foreign_spot():
    """
    把 data.json 中所有股票的「foreign」欄加總，換算成億元存入 fund_kline.json。
    換算公式（近似）：億元 ≈ 張數 × 平均股價(100元) / 100,000,000 * 1000（股/張）
                             ≈ 張數 × 100,000 / 100,000,000
                             ≈ 張數 / 1,000
    """
    print("  [3/5] 外資現貨買賣超（計算中）...")
    if not os.path.exists(DATA_FILE):
        print("    data.json 不存在，跳過")
        return

    data = load_json_dict(DATA_FILE)

    # 按日期加總所有股票的 foreign 買賣超（張）
    daily: dict[str, int] = {}
    for sid, info in data.items():
        for rec in info.get("records", []):
            d = rec["date"]
            daily[d] = daily.get(d, 0) + rec.get("foreign", 0)

    new_records = []
    for d, total_lots in sorted(daily.items()):
        billion = round(total_lots / 1000, 1)    # 億元（近似）
        color   = "#ef4444" if billion >= 0 else "#22c55e"
        new_records.append({"time": d, "value": billion, "color": color})

    existing = load_json_list(FUND_FILE)
    out = merge_and_save(existing, new_records, "time", FUND_FILE)
    print(f"    外資現貨：已儲存 {len(out)} 筆")


# ────────────────────────────────────────────────────────────────────────────
# 4. 散戶多空比（TAIFEX MXF）
# ────────────────────────────────────────────────────────────────────────────

def fetch_retail_ratio():
    """
    散戶（非法人）小台指期多空比。
    TAIFEX 每日公布「三大法人未平倉」，以：
      散戶淨部位 = 市場總未平倉 - 外資淨 - 投信淨 - 自營淨
      散戶多空比 = abs(散戶淨) / 市場總 * 100
    """
    print("  [4/5] 散戶多空比...")
    url = "https://www.taifex.com.tw/cht/3/futContractsDate"
    taifex_headers = {**HEADERS, "Referer": "https://www.taifex.com.tw/"}

    try:
        resp = requests.get(url, headers=taifex_headers, timeout=20)
        resp.encoding = "utf-8"
        soup = BeautifulSoup(resp.text, "lxml")

        net_by_identity: dict[str, int] = {}
        market_total = 0

        for table in soup.find_all("table"):
            text = table.get_text()
            if "小型臺指" not in text and "小台" not in text:
                continue

            rows = table.find_all("tr")
            in_section = False
            for row in rows:
                cells = [c.get_text(strip=True) for c in row.find_all(["th", "td"])]
                row_text = " ".join(cells)

                if "小型臺指" in row_text or "小台" in row_text:
                    in_section = True

                if not in_section:
                    continue

                # 找到各身份別淨口數
                for identity in ["外資", "投信", "自營商"]:
                    if identity in cells[0]:
                        for cell in reversed(cells):
                            clean = cell.replace(",", "").replace("+", "")
                            if re.match(r"^-?\d+$", clean):
                                net_by_identity[identity] = int(clean)
                                break

                # 找市場總未平倉（通常在最後幾欄的合計列）
                if "合計" in row_text or "全市場" in row_text:
                    for cell in reversed(cells):
                        clean = cell.replace(",", "")
                        if re.match(r"^\d{3,}$", clean):
                            market_total = int(clean)
                            break

        if not net_by_identity or market_total == 0:
            print("    無法解析散戶多空比，保留舊值")
            return

        inst_net = sum(net_by_identity.values())
        retail_net = market_total - abs(inst_net)   # 近似
        retail_ratio = round(abs(retail_net) / market_total * 100, 2) if market_total else 0

        existing_data = load_json_dict(RETAIL_FILE) or {"mxf_retail": []}
        existing_list = existing_data.get("mxf_retail", [])
        merged = {r["date"]: r for r in existing_list}
        merged[TODAY] = {
            "date":            TODAY,
            "retail_net_oi":   retail_net,
            "market_total_oi": market_total,
            "retail_ratio":    retail_ratio,
        }
        out = sorted(merged.values(), key=lambda x: x["date"])[-HISTORY_DAYS:]
        with open(RETAIL_FILE, "w", encoding="utf-8") as f:
            json.dump({"mxf_retail": out}, f, ensure_ascii=False, separators=(",", ":"))

        print(f"    散戶多空比: {retail_ratio}%，市場總 OI: {market_total:,d}")

    except Exception as e:
        print(f"    散戶多空比錯誤: {e}")

    time.sleep(TAIFEX_DELAY)


# ────────────────────────────────────────────────────────────────────────────
# 5. 融資維持率（TWSE）
# ────────────────────────────────────────────────────────────────────────────

def fetch_margin_ratio():
    """
    TWSE API: MI_MARGN
    上市融資維持率（上市整體平均維持成數）。
    """
    print("  [5/5] 融資維持率...")

    date_str = datetime.now().strftime("%Y%m%d")
    url      = "https://www.twse.com.tw/exchangeReport/MI_MARGN"
    params   = {"response": "json", "date": date_str, "selectType": "MS"}

    twse_ratio = None
    tpex_ratio = None

    try:
        resp = requests.get(url, params=params, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        j = resp.json()

        if j.get("stat") == "OK" and j.get("data"):
            # 找合計列（最後一列通常是合計）
            for row in reversed(j["data"]):
                for cell in row:
                    clean = str(cell).replace(",", "")
                    try:
                        v = float(clean)
                        # 維持率通常介於 100~300%
                        if 100 < v < 400:
                            twse_ratio = v
                            break
                    except ValueError:
                        continue
                if twse_ratio:
                    break

        print(f"    TWSE 融資維持率: {twse_ratio}%")
        time.sleep(TWSE_DELAY)

    except Exception as e:
        print(f"    TWSE 融資維持率錯誤: {e}")

    # TPEX 融資維持率（上櫃）
    try:
        tpex_url = (
            "https://www.tpex.org.tw/web/stock/margin_trading/"
            "margin_balance/margin_bal_result.php"
        )
        resp2 = requests.get(tpex_url, headers=HEADERS, timeout=15)
        # 簡單嘗試抓數字
        nums = re.findall(r"[\d,]+\.\d+", resp2.text)
        for n in nums:
            v = float(n.replace(",", ""))
            if 100 < v < 400:
                tpex_ratio = v
                break
    except Exception as e:
        print(f"    TPEX 融資維持率錯誤: {e}")

    # 合併寫回
    existing = load_json_dict(MARGIN_FILE) or {"TWSE": [], "TPEX": []}

    if twse_ratio is not None:
        twse_map = {r["date"]: r for r in existing.get("TWSE", [])}
        twse_map[TODAY] = {"date": TODAY, "ratio": twse_ratio}
        existing["TWSE"] = sorted(twse_map.values(), key=lambda x: x["date"])[-HISTORY_DAYS:]

    if tpex_ratio is not None:
        tpex_map = {r["date"]: r for r in existing.get("TPEX", [])}
        tpex_map[TODAY] = {"date": TODAY, "ratio": tpex_ratio}
        existing["TPEX"] = sorted(tpex_map.values(), key=lambda x: x["date"])[-HISTORY_DAYS:]

    with open(MARGIN_FILE, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, separators=(",", ":"))

    twse_n = len(existing.get("TWSE", []))
    tpex_n = len(existing.get("TPEX", []))
    print(f"    融資維持率：TWSE {twse_n} 筆，TPEX {tpex_n} 筆")


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
