"""积分理财科：① 积分省钱榜（公开） ② 积分周边墙 ③ 个人积分体检（--me，仅本地）。

算法：到店专用兑换券多为「积分 + 现金」形式（如 200 积分解锁 18.9 元购 2 份麦辣鸡翅），
价值 = (菜单同名单品现价合计 − 兑换现金价) ÷ 所需积分 × 10000 = 每万积分省钱数。
仅对能完整匹配菜单单品的券参与排名，匹配过程全部标注，宁可少算不瞎算。
用法：python -m mcd_lab.points [--me]
"""
import datetime as dt
import json
import re
from pathlib import Path

from .client import McpClient

ROOT = Path(__file__).resolve().parent.parent


def strip_size(name):
    return re.sub(r"[（(].*?[)）]", "", name)


def find_menu_items(desc, meals):
    """强匹配：菜单名（去括号后，≥3字）出现在券描述中；短名是长名子串时只留长名。"""
    matched = []
    for code, m in meals.items():
        try:
            price = float(m.get("currentPrice"))
        except (TypeError, ValueError):
            continue
        core = strip_size(m.get("name", ""))
        if len(core) >= 3 and core in desc:
            matched.append({"name": m.get("name"), "core": core, "price": price})
    deduped = [a for a in matched if not any(
        a is not b and a["core"] in b["core"] for b in matched)]
    return [{"name": x["name"], "price": x["price"]} for x in deduped]


def analyze_product(p, meals):
    spu = p.get("spuName", "")
    try:
        pts = float(p.get("point") or 0)
    except ValueError:
        return None
    m = re.match(r"^(\d+(?:\.\d+)?)元(.+)$", spu)
    if not m or pts <= 0:
        return {"kind": "wall", "spu": spu, "points": pts, "cat": p.get("catName", "")}
    cash = float(m.group(1))
    desc = m.group(2)
    qty = 1
    qm = re.search(r"(\d+)份", desc)
    if qm:
        qty = int(qm.group(1))
        desc = desc.replace(qm.group(0), "")
    # 任选 X 选 1：按最便宜的算（保守）
    if "/" in desc:
        alts = [a for a in re.split(r"[/、]", desc) if a]
        desc = alts[0]
    matched = find_menu_items(desc, meals)
    if not matched:
        return {"kind": "wall", "spu": spu, "points": pts, "cat": "到店专用(未能核价)"}
    menu_total = round(sum(x["price"] for x in matched) * qty, 2)
    savings = round(menu_total - cash, 2)
    if savings <= 0:
        return {"kind": "wall", "spu": spu, "points": pts, "cat": "到店专用(无省钱空间)"}
    return {
        "kind": "rank", "spu": spu, "points": pts, "cash": cash,
        "matched": [x["name"] for x in matched], "qty": qty,
        "menuTotal": menu_total, "savings": savings,
        "per10k": round(savings / pts * 10000, 2),
    }


def build_rows():
    snap_file = sorted((ROOT / "data" / "snapshots").glob("*.json"))[-1]
    snap = json.loads(snap_file.read_text())
    meals = snap["meals"]
    rank, wall = [], []
    for p in snap.get("pointsProducts") or []:
        r = analyze_product(p, meals)
        if not r:
            continue
        (rank if r["kind"] == "rank" else wall).append(r)
    rank.sort(key=lambda r: r["per10k"], reverse=True)
    return rank, wall


def render(rank, wall):
    date = dt.date.today().isoformat()
    L = [f"# 积分省钱榜 · {date}", "",
         "> 兑换券多为「积分 + 现金」形式。每万积分省钱 = (菜单同名单品现价合计 − 兑换现金价)"
         " ÷ 积分 × 10000，越高越划算。",
         "> 数据来自麦当劳官方 MCP（积分商城 × 实时菜单）自动估算，商品以门店实际供应为准。", ""]
    for i, r in enumerate(rank, 1):
        qty_note = f" ×{r['qty']}" if r["qty"] > 1 else ""
        L.append(f"{i}. **{r['spu']}** — {int(r['points'])} 积分 + ¥{r['cash']}，"
                 f"菜单现价合计约 ¥{r['menuTotal']}"
                 f"（{'、'.join(r['matched'])}{qty_note}），"
                 f"省 ¥{r['savings']} → 每万积分约省 **¥{r['per10k']}**")
    L += ["", "## 🧸 积分周边墙（无现金核价，纯情报）", ""]
    for w in wall:
        if w["points"] and w["points"] > 0:
            L.append(f"- {int(w['points'])} 积分：{w['spu']}（{w['cat']}）")
    L += ["", "---", "*麦麦研究所 · 积分理财科出品*"]
    return "\n".join(L)


def personal_report(c):
    acct = c.call_json("query-my-account").get("data", {})
    lot = c.call_json("query-lottery-info").get("data") or {}
    L = ["# 我的积分体检报告（仅本地生成，请勿公开）", ""]
    L.append(f"- 当前可用积分：**{acct.get('availablePoint')}**（{acct.get('currency','')}）")
    L.append(f"- 累计获得 {acct.get('accumulativePoint')} · 已使用 {acct.get('usedPoint')}"
             f" · 已过期 {acct.get('expiredPoint')}")
    L.append(f"- ⏰ 本月将过期：**{acct.get('currentMouthExpirePoint')}** · "
             f"下月将过期：{acct.get('nextMouthExpirePoint')}")
    L.append("")
    L.append(f"- 🎰 当前抽奖：{lot.get('activityName')}（{lot.get('drawPoint')} 积分/次，"
             f"{lot.get('activityStatusText')}）")
    prizes = [p.get("name") for p in (lot.get("prizes") or [])][:6]
    if prizes:
        L.append(f"- 奖品池：{' / '.join(prizes)}")
    L += ["", "> 快过期积分优先用于省钱榜前列；抽奖前先看奖品池再决定。"]
    return "\n".join(L)


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--me", action="store_true", help="生成个人积分体检（仅本地）")
    args = ap.parse_args()
    if args.me:
        print(personal_report(McpClient()))
        return
    rank, wall = build_rows()
    date = dt.date.today().isoformat()
    out = ROOT / "docs" / "market" / f"points-rank-{date}.md"
    out.write_text(render(rank, wall))
    payload = json.dumps({"rank": rank, "wall": wall}, ensure_ascii=False, indent=1)
    (ROOT / "data" / "market" / "points-rank.json").write_text(payload)
    site_data = ROOT / "docs" / "data"
    site_data.mkdir(parents=True, exist_ok=True)
    (site_data / "points-rank.json").write_text(payload)  # 稳定文件名，供在线 Demo 读取
    print(f"积分省钱榜已生成: {out}（{len(rank)} 条可核价 / {len(wall)} 条周边情报）")


if __name__ == "__main__":
    main()
