"""
run_all.py
──────────
主執行腳本。依序執行所有資料抓取步驟，並在最後建立排行榜。

執行順序很重要：
  1. fetch_institutional  → data.json（法人買賣超）
  2. fetch_kline          → Kline.json + 回填 data.json close/volume
  3. fetch_market         → 大盤5組資料
  4. fetch_vix            → vix.json
  5. fetch_etf            → etf_*.json
  6. build_insights       → insights.json / newcomers.json / explosive.json

用法：
  python scripts/run_all.py           # 一般更新（近 5 個交易日）
  python scripts/run_all.py --init    # 初始化（近 30 個交易日）
"""

import sys
import os
import traceback
from datetime import datetime

# 讓子模組找得到 config.py
sys.path.insert(0, os.path.dirname(__file__))

from fetch_institutional import update_data
from fetch_kline         import update_klines
from fetch_market        import update_market
from fetch_vix           import update_vix
from fetch_etf           import update_etfs
from build_insights      import build_insights


def run_step(label: str, fn, *args, **kwargs):
    """執行單一步驟，捕捉錯誤後繼續執行。"""
    sep = "─" * 50
    print(f"\n{sep}")
    print(f"  {label}")
    print(sep)
    try:
        fn(*args, **kwargs)
        print(f"  ✓ {label} 完成")
    except Exception:
        print(f"  ✗ {label} 發生錯誤：")
        traceback.print_exc()
        print(f"  → 繼續執行下一步...")


def main():
    is_init = "--init" in sys.argv

    print("=" * 50)
    print("  台股籌碼資料更新器")
    print(f"  執行時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  模式: {'初始化（30日）' if is_init else '一般更新（5日）'}")
    print("=" * 50)

    days_back = 30 if is_init else 5

    steps = [
        ("1/6  三大法人買賣超 (TWSE T86)",    update_data,      {"days_back": days_back}),
        ("2/6  個股 K 線 (yfinance)",          update_klines,    {}),
        ("3/6  大盤資料 (TWSE / TAIFEX)",      update_market,    {}),
        ("4/6  VIX 恐慌指數 (Yahoo Finance)", update_vix,       {}),
        ("5/6  ETF 成分股 (FinMind)",          update_etfs,      {}),
        ("6/6  建立排行榜 / newcomers",        build_insights,   {}),
    ]

    for label, fn, kwargs in steps:
        run_step(label, fn, **kwargs)

    print("\n" + "=" * 50)
    print(f"  全部完成！{datetime.now().strftime('%H:%M:%S')}")
    print("=" * 50)


if __name__ == "__main__":
    main()
