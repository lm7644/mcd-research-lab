"""行情部·每日快照采集：菜单/券池/活动日历/积分商城 → data/snapshots/YYYY-MM-DD.json

用法：python -m mcd_lab.snapshot [--store 1450713]
仅调用只读工具，不下单、不领券、不动积分。
"""
import argparse
import datetime as dt
import json
import os
import re
from pathlib import Path

from .client import McpClient, McpError

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STORE = os.environ.get("MCD_STORE_CODE", "1450713")


def parse_coupons_md(text):
    """从 available-coupons / query-store-coupons 的 markdown 中提取券名+状态。"""
    coupons = []
    for m in re.finditer(r"优惠券标题：(.+?)\\\n\s*状态：(.+?)(?:\\\n|$)", text):
        coupons.append({"title": m.group(1).strip(), "status": m.group(2).strip()})
    if not coupons:  # 兜底：逐行扫描
        title = None
        for line in text.splitlines():
            t = re.match(r"-\s*优惠券标题：(.+)", line)
            if t:
                title = t.group(1).strip()
            s = re.match(r"\s*状态：(.+)", line)
            if s and title:
                coupons.append({"title": title, "status": s.group(1).strip()})
                title = None
    return coupons


def parse_calendar_md(text):
    """campaign-calendar markdown → [{date, title, intro}]"""
    events = []
    blocks = re.split(r"####\s+", text)[1:]
    for b in blocks:
        header, _, rest = b.partition("\n")
        date = header.strip()
        titles = re.findall(r"\*\*活动标题\*\*：(.+?)$", rest, re.M)
        intros = re.findall(r"\*\*活动内容介绍\*\*：(.+?)(?=\n\s*\*\*|\Z)", rest, re.S)
        for i, t in enumerate(titles):
            events.append({
                "date": date,
                "title": t.strip(),
                "intro": (intros[i].strip()[:200] if i < len(intros) else ""),
            })
    return events


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default=DEFAULT_STORE)
    args = ap.parse_args()
    c = McpClient()

    categories, meals = c.menu(args.store)
    coupons = parse_coupons_md(c.call("available-coupons"))
    calendar = parse_calendar_md(c.call("campaign-calendar"))
    # 积分商城目录：官方可能下架/改名工具（2026-10-30 起 mall-points-products
    # 返回 unknown tool）。单点故障不应炸掉整条日报管道，缺失时降级为空列表。
    try:
        points_products = c.call_json("mall-points-products").get("data") or []
    except McpError as e:
        print(f"  ⚠️ 积分商城目录接口不可用，本期降级为空: {e}")
        points_products = []
    time_info = c.call_json("now-time-info").get("data") or {}

    snap = {
        "storeCode": args.store,
        "serverTime": time_info.get("datetime", ""),
        "capturedAt": dt.datetime.now().isoformat(timespec="seconds"),
        "categories": categories,
        "meals": meals,
        "couponPool": coupons,
        # 注意：不采集 query-store-coupons / query-my-coupons——它们返回
        # 用户本人券包与券码，属个人数据，不进入公开仓库
        "campaignCalendar": calendar,
        "pointsProducts": points_products,
    }
    out = ROOT / "data" / "snapshots" / f"{dt.date.today().isoformat()}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(snap, ensure_ascii=False, indent=1))
    print(f"快照完成: {out}")
    print(f"  菜单 {len(meals)} 项 / {len(categories)} 分类 | 券池 {len(coupons)} | "
          f"活动 {len(calendar)} | 积分商品 {len(points_products)}")


if __name__ == "__main__":
    main()
