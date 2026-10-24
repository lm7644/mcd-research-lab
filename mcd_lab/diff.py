"""行情部·差异引擎：对比两日快照 → 《麦麦行情日报》+ README 今日行情区块重写。

用法：python -m mcd_lab.diff            # 自动取最近两份快照
"""
import datetime as dt
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README_BEGIN = "<!-- MARKET:BEGIN -->"
README_END = "<!-- MARKET:END -->"


def load_snapshots():
    files = sorted((ROOT / "data" / "snapshots").glob("*.json"))
    if len(files) < 2:
        return None, json.loads(files[-1].read_text()), files[-1]
    return json.loads(files[-2].read_text()), json.loads(files[-1].read_text()), files[-1]


def yuan(v):
    """query-meals 的价格是元的字符串；容错处理。"""
    try:
        return float(str(v))
    except (TypeError, ValueError):
        return None


def diff_menus(old_meals, new_meals):
    changes = []
    for code, nm in new_meals.items():
        om = old_meals.get(code)
        if om is None:
            changes.append({"type": "new", "code": code, "name": nm["name"],
                            "price": yuan(nm.get("currentPrice"))})
            continue
        a, b = yuan(om.get("currentPrice")), yuan(nm.get("currentPrice"))
        if a is not None and b is not None and abs(a - b) >= 0.01:
            changes.append({"type": "up" if b > a else "down", "code": code,
                            "name": nm["name"], "from": a, "to": b,
                            "delta": round(b - a, 2)})
    for code, om in old_meals.items():
        if code not in new_meals:
            changes.append({"type": "gone", "code": code, "name": om["name"],
                            "price": yuan(om.get("currentPrice"))})
    return changes


def key_of_coupon(c):
    return c.get("title", "")


def diff_sets(old_list, new_list, key, label_add, label_del):
    old_keys = {key(x) for x in old_list}
    new_keys = {key(x) for x in new_list}
    added = [x for x in new_list if key(x) not in old_keys]
    removed = [x for x in old_list if key(x) not in new_keys]
    return added, removed


def render_report(today_snap, yesterday_snap, changes, coupons_diff, cal_diff, points_diff):
    date = today_snap.get("capturedAt", "")[:10]
    lines = [f"# 麦麦行情日报 · {date}", ""]
    meals = today_snap["meals"]
    lines.append(f"> 数据来源：麦当劳中国官方 MCP 实时接口 · 门店 {today_snap['storeCode']} · "
                 f"在售 {len(meals)} 项。本日报由 GitHub Action 自动生成，历史报告见本目录。")
    lines.append("")

    if yesterday_snap is None:
        lines.append("## 📌 首期基线")
        lines.append("")
        lines.append("今日为观察首日，建立价格基线。明日起开始输出逐日变动（涨价/降价/上新/下架/券池/活动）。")
    else:
        ups = [c for c in changes if c["type"] == "up"]
        downs = [c for c in changes if c["type"] == "down"]
        news = [c for c in changes if c["type"] == "new"]
        gones = [c for c in changes if c["type"] == "gone"]
        lines.append("## 🔺 涨价 / 🔻 降价")
        lines.append("")
        if not ups and not downs:
            lines.append("今日价格无变动，麦门平稳。")
        for c in ups + downs:
            icon = "🔺" if c["type"] == "up" else "🔻"
            lines.append(f"- {icon} **{c['name']}** ¥{c['from']} → ¥{c['to']}（{c['delta']:+.2f}）")
        if news:
            lines.append("")
            lines.append("## 🆕 上新")
            for c in news:
                lines.append(f"- **{c['name']}** ¥{c['price']}")
        if gones:
            lines.append("")
            lines.append("## 💀 下架")
            for c in gones:
                lines.append(f"- {c['name']}（昨日 ¥{c['price']}）")
        ca_add, ca_rm = cal_diff
        if ca_add or ca_rm:
            lines.append("")
            lines.append("## 📅 活动日历变动")
            for e in ca_add:
                lines.append(f"- 🆕 {e.get('date','')} {e.get('title','')}")
            for e in ca_rm:
                lines.append(f"- 🔚 {e.get('date','')} {e.get('title','')}")
    cp_add, cp_rm = coupons_diff
    if cp_add or cp_rm or yesterday_snap is None:
        lines.append("")
        lines.append("## 🎟️ 当前可领券池（麦麦省）")
        for c in today_snap["couponPool"]:
            lines.append(f"- {c['title']}（{c['status']}）")
    pp_add, pp_rm = points_diff
    if pp_add or pp_rm:
        lines.append("")
        lines.append("## 💰 积分商城变动")
        for p in pp_add[:10]:
            lines.append(f"- 🆕 {p.get('spuName')}（{p.get('point')} 积分）")
        for p in pp_rm[:10]:
            lines.append(f"- ⬇️ {p.get('spuName')}（{p.get('point')} 积分）")
    lines.append("")
    lines.append("---")
    lines.append("*麦麦研究所 · 行情部自动出品 · 数据来自麦当劳官方 MCP，仅供参考。*")
    return "\n".join(lines)


def rewrite_readme_block(report_md):
    readme = ROOT / "README.md"
    if not readme.exists():
        return
    text = readme.read_text()
    brief = "\n".join(report_md.splitlines()[2:20])  # 取日报核心段做摘要
    if README_BEGIN in text and README_END in text:
        pre = text.split(README_BEGIN)[0]
        post = text.split(README_END)[1]
        readme.write_text(f"{pre}{README_BEGIN}\n{brief}\n{README_END}{post}")
        print("README 今日行情区块已更新")


def main():
    old, new, new_file = load_snapshots()
    if old is None:
        changes, coupons_diff, cal_diff, points_diff = [], ([], []), ([], []), ([], [])
    else:
        changes = diff_menus(old["meals"], new["meals"])
        coupons_diff = diff_sets(old["couponPool"], new["couponPool"], key_of_coupon, "", "")
        cal_diff = diff_sets(old.get("campaignCalendar", []), new.get("campaignCalendar", []),
                             lambda e: f"{e.get('date')}|{e.get('title')}", "", "")
        points_diff = diff_sets(old.get("pointsProducts", []), new.get("pointsProducts", []),
                                lambda p: str(p.get("spuId")), "", "")
    report = render_report(new, old, changes, coupons_diff, cal_diff, points_diff)
    date_str = new["capturedAt"][:10]
    out = ROOT / "docs" / "market" / f"{date_str}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report)
    (ROOT / "data" / "market" / f"{date_str}.json").write_text(
        json.dumps({"changes": changes}, ensure_ascii=False, indent=1))
    site_data = ROOT / "docs" / "data"
    site_data.mkdir(parents=True, exist_ok=True)
    (site_data / "market-latest.json").write_text(json.dumps({
        "date": date_str, "isBaseline": old is None,
        "changes": changes, "couponPool": new.get("couponPool", []),
    }, ensure_ascii=False, indent=1))  # 稳定文件名，供在线 Demo 读取
    print(f"行情日报已生成: {out}")
    rewrite_readme_block(report)


if __name__ == "__main__":
    main()
