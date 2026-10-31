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
    # 积分商城目录：2026-10-30 官方将其改名 mall-points-products → query-mall-products
    # （返回结构与字段不变）。保留降级逻辑：未来再遇单工具故障不炸整条管道。
    try:
        points_products = c.call_json("query-mall-products").get("data") or []
    except McpError as e:
        print(f"  ⚠️ 积分商城目录接口不可用，本期降级为空: {e}")
        points_products = []
    time_info = c.call_json("now-time-info").get("data") or {}

    # 营养数据：官方自定义表格文本（[N]{列名}: + CSV 行）。成分基本静态，
    # 解析后写入稳定名 docs/data/nutrition.json，内容变化才落盘（CI 提交才非空）。
    nutrition = []
    try:
        nut_text = c.call_json("list-nutrition-foods").get("data") or ""
        m = re.search(r"\[(\d+)\]\{([^}]+)\}:\s*\n", nut_text)
        if m:
            cols = [x.strip() for x in m.group(2).split(",")]
            for line in nut_text[m.end():].splitlines():
                parts = [x.strip() for x in line.strip().split(",")]
                if len(parts) != len(cols):
                    continue
                row = {col: (None if v == "null" else v) for col, v in zip(cols, parts)}
                nutrition.append(row)
        else:
            print("  ⚠️ 营养数据格式未识别，跳过")
    except McpError as e:
        print(f"  ⚠️ 营养数据接口不可用，跳过: {e}")
    nut_file = ROOT / "docs" / "data" / "nutrition.json"
    nut_payload = json.dumps(nutrition, ensure_ascii=False, indent=1) + "\n"
    if nutrition and (not nut_file.exists() or nut_file.read_text() != nut_payload):
        nut_file.write_text(nut_payload)
        print(f"  营养数据已更新: {len(nutrition)} 款 → docs/data/nutrition.json")

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
