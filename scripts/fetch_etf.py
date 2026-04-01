"""
fetch_etf.py
────────────
用 FinMind 免費 API 抓取 ETF 成分股持股資料，
寫入 etf_{etf_id}_records.json。

FinMind API（免費，每日有限額，需要時可設定 token）：
  https://api.finmindtrade.com/api/v4/data
  dataset: TaiwanETFStockDetail
  data_id: ETF 代號（例 0050, 00980A）

如果要突破免費限額，請到 https://finmindtrade.com/ 申請帳號，
然後設定環境變數 FINMIND_TOKEN 或在 config 中填寫。
"""

import json
import os
import sys
import time
import requests
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(__file__))
from config import OUT_DIR, ETF_LIST

FINMIND_URL   = "https://api.finmindtrade.com/api/v4/data"
FINMIND_TOKEN = os.environ.get("FINMIND_TOKEN", "")   # 設定環境變數使用

REQUEST_DELAY = 1.5   # FinMind 免費版需要放慢速度


# ── 工具 ──────────────────────────────────────────────────────────────────

def fetch_etf_from_finmind(etf_id: str, start_date: str) -> list | None:
    """呼叫 FinMind API 取得 ETF 成分股歷史。"""
    params = {
        "dataset":    "TaiwanETFStockDetail",
        "data_id":    etf_id,
        "start_date": start_date,
    }
    if FINMIND_TOKEN:
        params["token"] = FINMIND_TOKEN

    try:
        resp = requests.get(FINMIND_URL, params=params, timeout=30)
        resp.raise_for_status()
        j = resp.json()

        if j.get("status") != 200:
            msg = j.get("msg", "unknown error")
            print(f"    FinMind {etf_id} 回傳錯誤: {msg}")
            return None

        data = j.get("data", [])
        print(f"    FinMind {etf_id}: 取得 {len(data)} 筆原始記錄")
        return data

    except Exception as e:
        print(f"    FinMind {etf_id} 例外: {e}")
        return None


def process_holdings(etf_id: str, etf_name: str, raw: list) -> dict | None:
    """
    把 FinMind 原始資料整理成前端需要的格式。

    FinMind TaiwanETFStockDetail 欄位：
      date, stock_id, stock_name, holding_shares, weight
    """
    if not raw:
        return None

    # 按日期分組
    by_date: dict[str, list] = {}
    for rec in raw:
        d = str(rec.get("date", ""))[:10]   # 取 YYYY-MM-DD 前 10 碼
        if d:
            by_date.setdefault(d, []).append(rec)

    if not by_date:
        return None

    dates_sorted = sorted(by_date.keys(), reverse=True)   # 最新在前
    latest_date  = dates_sorted[0]
    latest_recs  = by_date[latest_date]

    def get_historical_shares(sid: str, n_days: int):
        """找 n 個交易日前的持股張數。"""
        target = datetime.strptime(latest_date, "%Y-%m-%d") - timedelta(days=n_days)
        # 取最接近的歷史日期（≥ n_days 前）
        for d in dates_sorted[1:]:
            dt = datetime.strptime(d, "%Y-%m-%d")
            if (datetime.strptime(latest_date, "%Y-%m-%d") - dt).days >= n_days:
                for r in by_date[d]:
                    if str(r.get("stock_id", "")).strip() == sid:
                        return int(r.get("holding_shares", 0)), True
                return None, False   # ETF 在這天沒持有此股
        return None, False

    # 取得前一期日期（用於判斷 OUT）
    prev_date  = dates_sorted[1] if len(dates_sorted) > 1 else None
    prev_ids   = (
        {str(r.get("stock_id","")).strip() for r in by_date[prev_date]}
        if prev_date else set()
    )
    today_ids  = {str(r.get("stock_id","")).strip() for r in latest_recs}

    holdings = []

    # ── 目前持有的股票 ──
    for rec in latest_recs:
        sid    = str(rec.get("stock_id", "")).strip()
        sname  = str(rec.get("stock_name", sid)).strip()
        shares = int(rec.get("holding_shares", 0))
        weight = round(float(rec.get("weight", 0)), 2)

        sh10, ex10 = get_historical_shares(sid, 10)
        sh5,  ex5  = get_historical_shares(sid,  5)
        sh3,  ex3  = get_historical_shares(sid,  3)
        sh1,  ex1  = get_historical_shares(sid,  1)

        is_new = sid not in prev_ids  # 上一期沒有 → 新進

        holdings.append({
            "stock_id":  sid,
            "name":      sname,
            "shares":    shares,
            "weight":    weight,
            "change_10d": shares - (sh10 if sh10 is not None else shares),
            "change_5d":  shares - (sh5  if sh5  is not None else shares),
            "change_3d":  shares - (sh3  if sh3  is not None else shares),
            "change_1d":  shares - (sh1  if sh1  is not None else shares),
            "is_new": is_new,
            "is_out": False,
        })

    # ── 已移除的股票（前期有、現在沒有）──
    out_ids = prev_ids - today_ids
    if prev_date:
        for rec in by_date[prev_date]:
            sid = str(rec.get("stock_id", "")).strip()
            if sid in out_ids:
                holdings.append({
                    "stock_id":   sid,
                    "name":       str(rec.get("stock_name", sid)).strip(),
                    "shares":     0,
                    "weight":     0.0,
                    "change_10d": -int(rec.get("holding_shares", 0)),
                    "change_5d":  0,
                    "change_3d":  0,
                    "change_1d":  -int(rec.get("holding_shares", 0)),
                    "is_new":     False,
                    "is_out":     True,
                })

    # 按比重排序
    holdings.sort(key=lambda x: x["weight"], reverse=True)

    return {
        "etf_id":      etf_id,
        "name":        etf_name,
        "update_date": latest_date,
        "holdings":    holdings,
    }


# ── 主流程 ────────────────────────────────────────────────────────────────

def update_etfs():
    print("[fetch_etf] 開始抓取 ETF 成分股...")

    # 抓近 60 天資料（才能算 10 日變化）
    start_date = (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%d")

    for etf_id, etf_name in ETF_LIST:
        print(f"  {etf_id} {etf_name}...")

        # 先嘗試讀取既有檔
        out_file = os.path.join(OUT_DIR, f"etf_{etf_id}_records.json")

        raw = fetch_etf_from_finmind(etf_id, start_date)
        if raw:
            result = process_holdings(etf_id, etf_name, raw)
            if result:
                with open(out_file, "w", encoding="utf-8") as f:
                    json.dump(result, f, ensure_ascii=False, separators=(",", ":"))
                n_hold = sum(1 for h in result["holdings"] if not h["is_out"])
                print(f"    {etf_id}: {n_hold} 支持股（含 OUT {sum(1 for h in result['holdings'] if h['is_out'])} 支）")
        else:
            print(f"    {etf_id}: 取得失敗，保留舊檔")

        time.sleep(REQUEST_DELAY)

    print("[fetch_etf] 完成")


if __name__ == "__main__":
    update_etfs()
