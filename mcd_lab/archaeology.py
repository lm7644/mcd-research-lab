"""考古部：枚举麦当劳套餐的选配空间（rounds × choices × 特调）→ 隐藏吃法图鉴。

每个套餐在官方点餐接口里都是一棵组合树：主食轮/小食轮/饮料轮，选项可替换，
部分选项还带「特调」（加酱、加吉士、去冰、换燕麦奶……多数 0 元）。
考古部把整棵树挖出来存档，生成人话版图鉴。
用法：python -m mcd_lab.archaeology [--limit 80] [--only 巨无霸]
"""
import argparse
import datetime as dt
import json
import re
import time
from pathlib import Path

from .client import McpClient

ROOT = Path(__file__).resolve().parent.parent


def walk_modification(mod):
    """modification.items[].values[] → [{name, price(元), max}]"""
    out = []
    for item in (mod or {}).get("items", []):
        for v in item.get("values", []):
            out.append({
                "name": v.get("name"),
                "price": round(int(v.get("price") or 0) / 100, 2),
                "max": v.get("maxQuantity", 1),
            })
    # 同名合并（同名不同 key 的少见，保留最大价）
    merged = {}
    for m in out:
        k = m["name"]
        if k not in merged:
            merged[k] = m
    return list(merged.values())


def extract_tree(detail):
    rounds = []
    for r in detail.get("rounds", []):
        choices = []
        for ch in r.get("choices", []):
            choices.append({
                "name": ch.get("name"),
                "isDefault": ch.get("isDefault") == 1,
                "supportModify": bool(ch.get("supportModify")),
                "modifications": walk_modification(ch.get("modification")),
            })
        rounds.append({
            "name": r.get("name"),
            "min": r.get("minQuantity"),
            "max": r.get("maxQuantity"),
            "choices": choices,
        })
    return rounds


def analyze(rounds):
    """从树里提炼「考古发现」。"""
    free_mods, paid_mods, swaps, defaults = [], [], [], []
    for r in rounds:
        for ch in r["choices"]:
            if ch["isDefault"]:
                defaults.append(f"{r['name']}：{ch['name']}")
            elif not ch["modifications"]:
                swaps.append(f"{r['name']}：{ch['name']}")
            for m in ch["modifications"]:
                tag = "默认含" if ch["isDefault"] else "搭配"
                rec = {"where": f"{r['name']} · {ch['name']}", **m}
                (free_mods if m["price"] == 0 else paid_mods).append(rec)
    seen, uniq_free = set(), []
    for m in free_mods:
        if m["name"] not in seen:
            seen.add(m["name"])
            uniq_free.append(m)
    return {"defaults": defaults, "swaps": swaps,
            "freeMods": uniq_free, "paidMods": paid_mods}


def render_page(meal_name, price, tree, found):
    L = [f"# {meal_name} 组合考古", ""]
    try:
        L.append(f"> 菜单现价 ¥{float(price)}。以下选配与特调全部来自麦当劳官方 MCP "
                 f"点餐接口的真实返回，编号见 data/archaeology.json。")
    except (TypeError, ValueError):
        L.append("> 以下选配与特调全部来自麦当劳官方 MCP 点餐接口的真实返回。")
    L.append("")
    L.append("## 📋 默认搭配")
    for d in found["defaults"]:
        L.append(f"- {d}")
    if not found["defaults"]:
        L.append("- （单品，无套餐轮次）")
    L.append("")
    L.append("## 🔄 可替换项")
    for s in found["swaps"]:
        L.append(f"- {s}")
    if not found["swaps"]:
        L.append("- （无可替换项）")
    L.append("")
    if found["freeMods"]:
        L.append("## 🆓 0 元特调（免费加/去/换）")
        for m in found["freeMods"]:
            extra = f"（最多 {m['max']} 份）" if m.get("max", 1) > 1 else ""
            L.append(f"- {m['name']}{extra} · {m['where']}")
    if found["paidMods"]:
        L.append("")
        L.append("## 💸 付费特调")
        for m in found["paidMods"]:
            L.append(f"- {m['name']} +¥{m['price']} · {m['where']}")
    L += ["", "## 🌳 原始组合树", ""]
    for r in tree:
        L.append(f"**{r['name']}**（{r['min']}~{r['max']} 选）")
        for ch in r["choices"]:
            mark = "✅" if ch["isDefault"] else "·"
            mod = ""
            if ch["modifications"]:
                names = "、".join(m["name"] + ("" if m["price"] == 0
                                               else f"+¥{m['price']}")
                                  for m in ch["modifications"])
                mod = f" ｜特调：{names}"
            L.append(f"- {mark} {ch['name']}{mod}")
        L.append("")
    L.append("---")
    L.append("*麦麦研究所 · 考古部出品 · 选配以门店实际供应为准*")
    return "\n".join(L)


def slug(name):
    s = re.sub(r"[^\w\u4e00-\u9fff]+", "-", name).strip("-")
    return s[:40] or "meal"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=80)
    ap.add_argument("--only", help="只考古名称包含该关键词的餐品")
    args = ap.parse_args()

    c = McpClient()
    snap_file = sorted((ROOT / "data" / "snapshots").glob("*.json"))[-1]
    snap = json.loads(snap_file.read_text())
    store = snap["storeCode"]
    meals = snap["meals"]
    order = []
    for cat in snap["categories"]:
        for it in cat.get("meals", []):
            code = it.get("code") if isinstance(it, dict) else None
            if code and code in meals:
                order.append(code)
    for code in meals:
        if code not in order:
            order.append(code)
    if args.only:
        order = [x for x in order if args.only in meals[x]["name"]]

    out_dir = ROOT / "docs" / "archaeology"
    out_dir.mkdir(parents=True, exist_ok=True)
    archive, stats = {}, []
    done = 0
    for code in order:
        if done >= args.limit:
            break
        if code in archive:  # 同一套餐会出现在多个分类下，只考古一次
            continue
        name = meals[code]["name"]
        try:
            detail = c.meal_detail(store, code)
        except Exception as e:  # 单品失败不阻塞考古
            print(f"  skip {name}: {e}")
            continue
        if not detail.get("rounds"):
            continue
        tree = extract_tree(detail)
        found = analyze(tree)
        archive[code] = {"name": name, "rounds": tree, "found": found}
        page = render_page(name, meals[code].get("currentPrice"), tree, found)
        (out_dir / f"{slug(name)}.md").write_text(page)
        stats.append((name, len(found["freeMods"]), len(found["swaps"]),
                      sum(len(r["choices"]) for r in tree)))
        done += 1
        time.sleep(0.4)
    (ROOT / "data" / "archaeology.json").write_text(
        json.dumps(archive, ensure_ascii=False, indent=1))
    site_data = ROOT / "docs" / "data"
    site_data.mkdir(parents=True, exist_ok=True)
    (site_data / "archaeology-summary.json").write_text(json.dumps([
        {"name": a["name"],
         "file": f"archaeology/{slug(a['name'])}.md",
         "freeMods": len(a["found"]["freeMods"]),
         "swaps": len(a["found"]["swaps"]),
         "nodes": sum(len(r["choices"]) for r in a["rounds"])}
        for a in archive.values()
    ], ensure_ascii=False, indent=1))  # 稳定文件名，供在线 Demo 读取

    # 考古摘要
    stats.sort(key=lambda x: x[1] + x[2], reverse=True)
    L = [f"# 考古发现摘要 · {dt.date.today().isoformat()}", "",
         f"> 已考古 {len(stats)} 款餐品的官方选配空间，全部来自麦当劳 MCP 真实接口。",
         "", "## 自由度排行榜（免费特调 + 可替换项）", ""]
    for i, (name, fm, sw, total) in enumerate(stats[:15], 1):
        L.append(f"{i}. **{name}** — {fm} 项免费特调 / {sw} 个替换位 / 组合树 {total} 节点")
    L += ["", "## 全场 0 元特调清单（免费加/去/换）", ""]
    seen = set()
    for code, a in archive.items():
        for m in a["found"]["freeMods"]:
            if m["name"] not in seen:
                seen.add(m["name"])
                L.append(f"- {m['name']}（{m['where']}）")
    (ROOT / "docs" / "archaeology" / "INDEX.md").write_text("\n".join(L))
    print(f"考古完成：{len(stats)} 款有选配空间，图鉴 {out_dir}，摘要 INDEX.md")


if __name__ == "__main__":
    main()
