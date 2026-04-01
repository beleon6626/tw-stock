"""
build_insights.py
─────────────────
從 data.json 計算各種排行榜，輸出：

  insights.json    ← 外資/投信 買超/賣超排行（1日/5日/10日）
  newcomers.json   ← 近10日首次進入前30名的股票
  explosive.json   ← 今日買超量異常放大的股票
"""

import json
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(__file__))
from config import OUT_DIR

DATA_FILE      = os.path.join(OUT_DIR, "data.json")
INSIGHTS_FILE  = os.path.join(OUT_DIR, "insights.json")
NEWCOMERS_FILE = os.path.join(OUT_DIR, "newcomers.json")
EXPLOSIVE_FILE = os.path.join(OUT_DIR, "explosive.json")

TOP_N = 50   # 每個排行保留前 N 名


# ── 工具 ──────────────────────────────────────────────────────────────────

def safe_ratio(net: float, vol: float) -> float:
    """net / vol * 100，vol=0 時回傳 0。"""
    if vol <= 0:
        return 0.0
    return round(net / vol * 100, 2)


def sum_field(records: list, field: str) -> int:
    return sum(r.get(field, 0) for r in records)


def avg_field(records: list, field: str) -> float:
    if not records:
        return 0.0
    return sum_field(records, field) / len(records)


# ── 主流程 ────────────────────────────────────────────────────────────────

def build_insights():
    print("[build_insights] 開始計算排行榜...")

    if not os.path.exists(DATA_FILE):
        print("  data.json 不存在，請先執行 fetch_institutional.py")
        return

    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data: dict = json.load(f)

    today_str = datetime.now().strftime("%Y%m%d")

    # ── 為每支股票計算各期間統計 ──────────────────────────────────────────
    stock_stats = []

    for sid, info in data.items():
        name    = info.get("name", sid)
        records = info.get("records", [])
        if not records:
            continue

        r1   = records[-1:]    # 最後 1 日
        r5   = records[-5:]    # 最後 5 日
        r10  = records[-10:]   # 最後 10 日

        vol_1d  = max(avg_field(r1,  "volume"), 1)
        vol_5d  = max(avg_field(r5,  "volume"), 1)
        vol_10d = max(avg_field(r10, "volume"), 1)

        stock_stats.append({
            "stock_id":    sid,
            "name":        name,
            # 1 日
            "foreign_1d":  sum_field(r1,  "foreign"),
            "invest_1d":   sum_field(r1,  "invest"),
            "vol_1d":      vol_1d,
            # 5 日
            "foreign_5d":  sum_field(r5,  "foreign"),
            "invest_5d":   sum_field(r5,  "invest"),
            "vol_5d":      vol_5d,
            # 10 日
            "foreign_10d": sum_field(r10, "foreign"),
            "invest_10d":  sum_field(r10, "invest"),
            "vol_10d":     vol_10d,
            # 供 newcomer / explosive 使用
            "records":     records,
        })

    # ── 建立排行榜 ────────────────────────────────────────────────────────

    def make_ranking(
        stats:    list,
        net_key:  str,
        vol_key:  str,
        ratio_key: str,
        positive: bool,
    ) -> list:
        """
        positive=True  → 買超排行（net > 0）
        positive=False → 賣超排行（net < 0）
        """
        filtered = [
            s for s in stats
            if (s[net_key] > 0 if positive else s[net_key] < 0)
        ]
        # 依絕對值大小排序
        filtered.sort(key=lambda s: abs(s[net_key]), reverse=True)
        filtered = filtered[:TOP_N]

        result = []
        for s in filtered:
            ratio = safe_ratio(s[net_key], s[vol_key])
            if not positive:
                ratio = -abs(ratio)
            result.append({
                "stock_id":  s["stock_id"],
                "name":      s["name"],
                ratio_key:   ratio,
            })
        return result

    insights = {
        "date": today_str,
        # 1 日
        "foreign_ratio_ranking":          make_ranking(stock_stats, "foreign_1d",  "vol_1d",  "foreign_ratio", True),
        "foreign_ratio_sell_ranking":     make_ranking(stock_stats, "foreign_1d",  "vol_1d",  "foreign_ratio", False),
        "invest_ratio_ranking":           make_ranking(stock_stats, "invest_1d",   "vol_1d",  "invest_ratio",  True),
        "invest_ratio_sell_ranking":      make_ranking(stock_stats, "invest_1d",   "vol_1d",  "invest_ratio",  False),
        # 5 日
        "foreign_ratio_5d_ranking":       make_ranking(stock_stats, "foreign_5d",  "vol_5d",  "foreign_ratio", True),
        "foreign_ratio_5d_sell_ranking":  make_ranking(stock_stats, "foreign_5d",  "vol_5d",  "foreign_ratio", False),
        "invest_ratio_5d_ranking":        make_ranking(stock_stats, "invest_5d",   "vol_5d",  "invest_ratio",  True),
        "invest_ratio_5d_sell_ranking":   make_ranking(stock_stats, "invest_5d",   "vol_5d",  "invest_ratio",  False),
        # 10 日
        "foreign_ratio_10d_ranking":      make_ranking(stock_stats, "foreign_10d", "vol_10d", "foreign_ratio", True),
        "foreign_ratio_10d_sell_ranking": make_ranking(stock_stats, "foreign_10d", "vol_10d", "foreign_ratio", False),
        "invest_ratio_10d_ranking":       make_ranking(stock_stats, "invest_10d",  "vol_10d", "invest_ratio",  True),
        "invest_ratio_10d_sell_ranking":  make_ranking(stock_stats, "invest_10d",  "vol_10d", "invest_ratio",  False),
    }

    with open(INSIGHTS_FILE, "w", encoding="utf-8") as f:
        json.dump(insights, f, ensure_ascii=False, separators=(",", ":"))
    print(f"  insights.json 已儲存（各榜前 {TOP_N} 名）")

    # ── Newcomers：今日進榜但近 10 日沒上榜 ──────────────────────────────

    top30_today = {
        s["stock_id"]
        for s in stock_stats
        if s["foreign_1d"] > 0
    }[:30]  # 取前 30

    # 實際上要用 insights 的排名清單
    top30_ids = {s["stock_id"] for s in insights["foreign_ratio_ranking"][:30]}

    # 判斷「近 10 日是否曾出現在前列」：用 10 日累計買超量判斷活躍度
    was_active_10d: set[str] = set()
    for s in stock_stats:
        # 如果最近 10 日（排除今天）外資買超超過 500 張，視為曾活躍
        past_foreign = sum(
            r.get("foreign", 0)
            for r in s["records"][:-1][-9:]   # 前 9 天
        )
        if past_foreign > 500:
            was_active_10d.add(s["stock_id"])

    newcomers = [
        {"stock_id": s["stock_id"], "name": s["name"]}
        for s in stock_stats
        if s["stock_id"] in top30_ids and s["stock_id"] not in was_active_10d
    ]

    with open(NEWCOMERS_FILE, "w", encoding="utf-8") as f:
        json.dump(
            {"date": today_str, "newcomers": newcomers},
            f, ensure_ascii=False, separators=(",", ":")
        )
    print(f"  newcomers.json：{len(newcomers)} 支新進榜")

    # ── Explosive：今日外資買超 > 近10日日均的 2 倍 ─────────────────────

    explosive = []
    for s in stock_stats:
        net_today  = s["foreign_1d"]
        if net_today <= 0:
            continue

        # 近 10 日（不含今天）的日均外資買超
        past_recs = s["records"][:-1][-10:]
        if not past_recs:
            continue

        past_avg = avg_field(past_recs, "foreign")

        # 條件：今日買超 > 過去均值 2 倍，且過去均值 > 0
        if past_avg > 0 and net_today > past_avg * 2:
            explosive.append({
                "stock_id":  s["stock_id"],
                "name":      s["name"],
                "foreign_1d": net_today,
                "past_avg":   round(past_avg, 0),
                "ratio":      round(net_today / past_avg, 1),
            })

    explosive.sort(key=lambda x: x["ratio"], reverse=True)
    explosive = explosive[:15]

    with open(EXPLOSIVE_FILE, "w", encoding="utf-8") as f:
        json.dump(
            {"date": today_str, "explosive": explosive},
            f, ensure_ascii=False, separators=(",", ":")
        )
    print(f"  explosive.json：{len(explosive)} 支爆量股")

    print("[build_insights] 完成")


if __name__ == "__main__":
    build_insights()
