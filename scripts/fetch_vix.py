"""
fetch_vix.py
────────────
用 yfinance 抓取 VIX（美股恐慌指數）與 VIXTWN（台灣波動率指數），
寫入 vix.json。

Yahoo Finance 代號：
  ^VIX    → CBOE Volatility Index（美）
  ^TWIVIX → Taiwan Volatility Index（台）
"""

import json
import os
import sys
from datetime import datetime

import yfinance as yf

sys.path.insert(0, os.path.dirname(__file__))
from config import OUT_DIR

VIX_FILE = os.path.join(OUT_DIR, "vix.json")

# 各 VIX 等級對應標籤和顏色
VIX_LEVELS = [
    (15,  "極度樂觀", "green"),
    (25,  "正常",     "blue"),
    (35,  "恐慌",     "orange"),
    (999, "極度恐慌", "red"),
]


def get_vix_level(val: float) -> tuple[str, str]:
    for threshold, label, color in VIX_LEVELS:
        if val < threshold:
            return label, color
    return "極度恐慌", "red"


def safe_get_price(ticker_sym: str) -> float | None:
    """安全取得最新價格，失敗回傳 None。"""
    try:
        tk = yf.Ticker(ticker_sym)
        # 先嘗試 fast_info（快，無需下載歷史）
        price = tk.fast_info.get("last_price") or tk.fast_info.get("lastPrice")
        if price and price > 0:
            return round(float(price), 2)
        # 備用：下載最近 5 日歷史取最後一筆
        df = tk.history(period="5d")
        if not df.empty:
            return round(float(df["Close"].iloc[-1]), 2)
    except Exception as e:
        print(f"    {ticker_sym} 錯誤: {e}")
    return None


def update_vix():
    print("[fetch_vix] 抓取 VIX 資料...")

    vix     = safe_get_price("^VIX")
    vixtwn  = safe_get_price("^TWIVIX")

    if vix is None:
        print("  VIX 取得失敗，保留舊值")
        # 嘗試保留現有檔案不覆蓋
        return

    label, color = get_vix_level(vix)

    data = {
        "vix":        vix,
        "vixtwn":     vixtwn if vixtwn else 0,
        "vix_label":  label,
        "vix_color":  color,
        "source":     "yahoo_finance_v8",
        "timestamp":  datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    with open(VIX_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))

    print(f"  VIX={vix}，VIXTWN={vixtwn}，等級={label}({color})")
    print("[fetch_vix] 完成")


if __name__ == "__main__":
    update_vix()
