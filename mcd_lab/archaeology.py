"""考古部：枚举麦当劳套餐的选配空间（rounds × choices × 特调）→ 隐藏吃法图鉴。

每个套餐在官方点餐接口里都是一棵组合树：主食轮/小食轮/饮料轮，选项可替换，
部分选项还带「特调」（加酱、加吉士、去冰、换燕麦奶……多数 0 元）。
考古部把整棵树挖出来存档，生成人话版图鉴。
用法：python -m mcd_lab.archaeology [--limit 80] [--only 巨无霸]
"""
import argparse
import json
import re
import time
from pathlib import Path

from . import clock
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


META_PREFIX = "<!-- arch:"


def page_meta(name, found, tree):
    """页面内嵌机器可读元数据：摘要由目录扫描生成，不再依赖内存中的 archive。"""
    return META_PREFIX + json.dumps({
        "name": name,
        "freeMods": len(found["freeMods"]),
        "swaps": len(found["swaps"]),
        "nodes": sum(len(r["choices"]) for r in tree),
        "freeNames": [m["name"] for m in found["freeMods"]],
    }, ensure_ascii=False) + " -->"


def render_page(meal_name, price, tree, found):
    L = [f"# {meal_name} 组合考古", page_meta(meal_name, found, tree), ""]
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
    snap_files = sorted((ROOT / "data" / "snapshots").glob("*.json"))
    if not snap_files:
        raise SystemExit("未找到任何快照，请先运行 python -m mcd_lab.snapshot")
    snap = json.loads(snap_files[-1].read_text(encoding="utf-8"))
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
    archived_names, archived_slugs = set(), set()
    for code in order:
        if done >= args.limit:
            break
        if code in archive:  # 同一套餐会出现在多个分类下，只考古一次
            continue
        name = meals[code]["name"]
        if name in archived_names or slug(name) in archived_slugs:  # 同名/同文件名只留一份
            continue
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
        archived_names.add(name)
        archived_slugs.add(slug(name))
        page = render_page(name, meals[code].get("currentPrice"), tree, found)
        (out_dir / f"{slug(name)}.md").write_text(page, encoding="utf-8")
        done += 1
        time.sleep(0.4)
    (ROOT / "data" / "archaeology.json").write_text(
        json.dumps(archive, ensure_ascii=False, indent=1), encoding="utf-8")

    # 清理已不在当前菜单里的旧图鉴页（完整跑才清理）。
    # 只按「菜单里还有没有这款」判断，不按本次 --limit 的采集范围，
    # 否则 --limit 80 会把限额外的存量图鉴误删。
    if not args.only:
        live_pages = {f"{slug(meals[code]['name'])}.md" for code in meals} | {"INDEX.md"}
        for stale in out_dir.glob("*.md"):
            if stale.name not in live_pages:
                stale.unlink()

    entries = build_summary(out_dir, clock.today(snap.get("serverTime")).isoformat())
    pages = len([p for p in out_dir.glob("*.md") if p.name != "INDEX.md"])
    print(f"考古完成：本次采集 {done} 款，图鉴 {pages} 个文件，摘要 {len(entries)} 条")


def parse_legacy_page(path, text):
    """旧版页面没有内嵌元数据，按 markdown 结构还原摘要字段。"""
    m = re.search(r"^# (.+?) 组合考古", text, re.MULTILINE)
    name = m.group(1).strip() if m else path.stem
    sections, cur = {}, None
    for line in text.splitlines():
        if line.startswith("## "):
            cur = line[3:].strip()
            sections[cur] = []
        elif cur is not None and line.startswith("- "):
            sections[cur].append(line[2:].strip())
    free = sections.get("🆓 0 元特调（免费加/去/换）", [])
    swaps = sections.get("🔄 可替换项", [])
    tree = sections.get("🌳 原始组合树", [])
    return {
        "name": name,
        "freeMods": len(free),
        "swaps": len(swaps),
        "nodes": sum(1 for x in tree if x.startswith(("✅", "·"))),
        "freeNames": [x.split(" · ")[0] for x in free],
    }


def build_summary(out_dir, date):
    """扫描目录里的图鉴页，程序生成 INDEX.md 与 archaeology-summary.json。

    summary 的唯一事实来源是磁盘上的页面（每页内嵌 META_PREFIX 元数据），
    数量、排序、去重都与目录一致，不再手写或依赖内存态。
    """
    entries = []
    files = [p for p in out_dir.glob("*.md") if p.name != "INDEX.md"]
    for path in files:
        text = path.read_text(encoding="utf-8")
        meta = None
        for line in text.splitlines():
            if line.startswith(META_PREFIX) and line.endswith("-->"):
                meta = json.loads(line[len(META_PREFIX):-3].strip())
                break
        if meta is None:  # 兼容旧版页面（无内嵌元数据）：按正文结构解析
            meta = parse_legacy_page(path, text)
        meta["file"] = f"archaeology/{path.name}"
        entries.append(meta)
    # 摘要唯一事实来源是目录里的文件：条目数必须等于文件数，且不能有同名重复。
    names = [e["name"] for e in entries]
    dups = sorted({n for n in names if names.count(n) > 1})
    if dups:
        raise SystemExit(f"考古目录存在同名图鉴，摘要无法自洽：{'、'.join(dups)}"
                         f"（文件 {len(files)} / 条目 {len(entries)}）")
    # 排序键固定：免费特调+替换位 → 节点数 → 名称
    entries.sort(key=lambda e: (-(e["freeMods"] + e["swaps"]), -e["nodes"], e["name"]))

    site_data = ROOT / "docs" / "data"
    site_data.mkdir(parents=True, exist_ok=True)
    (site_data / "archaeology-summary.json").write_text(json.dumps([
        {"name": e["name"], "file": e["file"], "freeMods": e["freeMods"],
         "swaps": e["swaps"], "nodes": e["nodes"]}
        for e in entries
    ], ensure_ascii=False, indent=1), encoding="utf-8")

    L = [f"# 考古发现摘要 · {date}", "",
         f"> 已考古 {len(entries)} 款餐品的官方选配空间，全部来自麦当劳 MCP 真实接口。"
         f"摘要由 {len(entries)} 个图鉴文件程序生成。",
         "", "## 自由度排行榜（免费特调 + 可替换项）", ""]
    for i, e in enumerate(entries[:15], 1):
        L.append(f"{i}. **{e['name']}** — {e['freeMods']} 项免费特调 / "
                 f"{e['swaps']} 个替换位 / 组合树 {e['nodes']} 节点")
    L += ["", "## 全场 0 元特调清单（免费加/去/换）", ""]
    seen_names = set()
    for e in entries:
        for n in e.get("freeNames", []):
            if n not in seen_names:
                seen_names.add(n)
                L.append(f"- {n}")
    (out_dir / "INDEX.md").write_text("\n".join(L), encoding="utf-8")
    return entries


if __name__ == "__main__":
    main()
