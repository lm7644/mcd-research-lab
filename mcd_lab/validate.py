"""数据完整性校验：对比最近两份快照，四类采集量分别判断「采集不全 / 真实变动」。

判定口径（每类独立阈值）：
- 时段异常（营业时段外采集，北京 10:30–22:00 之外）→ 采集不全，中止；
- 分类整体缺失（昨日有的菜单分类今日一个都没有）→ 采集不全，中止；
- 某一类整类归零 → 采集不全，中止；
- 单类跌幅超过该类阈值：时段异常时判采集不全中止，营业时段内判真实变动放行（打告警）。

采集不全时退出码 2：workflow 视为「本次跳过发布」，不当作流程失败（不发失败告警）。
真异常（读文件/解析失败等）退出码 1，workflow 照常失败。
人工放行（仅限确认过的真实缩减，如门店调整菜单）：--allow-shrink。时段异常不可放行。

用法：python -m mcd_lab.validate [--allow-shrink] [--prev PATH --cur PATH]
"""
import argparse
import json
import sys
from pathlib import Path

from . import clock

ROOT = Path(__file__).resolve().parent.parent

# 类别 → (快照字段, 相对下降阈值, 中文名)
CATS = [
    ("meals", "meals", 0.10, "菜单"),
    ("coupons", "couponPool", 0.30, "券池"),
    ("points", "pointsProducts", 0.20, "积分商品"),
    ("calendar", "campaignCalendar", 0.30, "活动日历"),
]
# 全日菜单上齐 ≈ 10:30，打烊 ≈ 22:00（北京时间）。早餐/夜间采集都落在这个窗口外。
OPEN_MIN, CLOSE_MIN = 10 * 60 + 30, 22 * 60


def cat_names(snap):
    return [c.get("name") for c in snap.get("categories") or [] if isinstance(c, dict)]


def minute_of(ts):
    return None if ts is None else ts.hour * 60 + ts.minute


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--allow-shrink", action="store_true",
                    help="人工放行采集量下降（仅限已确认的真实缩减；时段异常不可放行）")
    ap.add_argument("--prev", help="基准快照路径（默认倒数第二份）")
    ap.add_argument("--cur", help="本次快照路径（默认最后一份）")
    args = ap.parse_args()

    if args.prev and args.cur:
        prev_path, cur_path = Path(args.prev), Path(args.cur)
    else:
        files = sorted((ROOT / "data" / "snapshots").glob("*.json"))
        if len(files) < 2:
            print("只有一份快照，跳过校验")
            return 0
        prev_path, cur_path = files[-2], files[-1]

    prev = json.loads(prev_path.read_text(encoding="utf-8"))
    cur = json.loads(cur_path.read_text(encoding="utf-8"))

    ts = clock.parse_server_time(cur.get("serverTime"))
    mins = minute_of(ts)
    off_hours = mins is not None and not (OPEN_MIN <= mins < CLOSE_MIN)
    missing_cats = [c for c in cat_names(prev) if c not in cat_names(cur)]

    incomplete = []  # 必须中止
    if off_hours:
        incomplete.append(f"采集时段 {ts:%H:%M} 不在营业时段 "
                          f"{OPEN_MIN // 60:02d}:{OPEN_MIN % 60:02d}–{CLOSE_MIN // 60:02d}:00 内")
    if missing_cats:
        incomplete.append(f"分类整体缺失 {len(missing_cats)} 个："
                          + "、".join(c.replace("\n", "") for c in missing_cats))

    print(f"对比：{prev_path.name} → {cur_path.name}（serverTime={ts or '缺失'}）")
    print(f"{'类别':<6}{'上一份':>6}{'本次':>6}{'变化':>9}  判定")
    warnings = []
    for _, key, threshold, cn in CATS:
        p = len(prev.get(key) or [])
        c = len(cur.get(key) or [])
        pct = 0.0 if not p else (c - p) / p
        if p > 0 and c == 0:
            verdict = "采集不全（整类归零）"
            incomplete.append(f"{cn} {p} → 0")
        elif -pct > threshold:
            if off_hours:
                verdict = "采集不全（时段外骤降）"
                incomplete.append(f"{cn} {p} → {c}（{pct:+.1%}，营业时段外）")
            else:
                verdict = f"真实变动（超过阈值 {threshold:.0%}）"
                warnings.append(f"{cn} {p} → {c}（{pct:+.1%}）")
        else:
            verdict = "正常"
        print(f"{cn:<6}{p:>8}{c:>8}{pct:>+9.1%}  {verdict}")

    if incomplete:
        msg = "；".join(incomplete)
        if args.allow_shrink and not off_hours:
            print(f"::warning::人工放行（--allow-shrink），不中止：{msg}")
            return 0
        print("::warning::采集不全，跳过发布：" + msg)
        return 2
    for w in warnings:
        print(f"::warning::单类下降超过阈值但无采集不全信号，按真实变动放行：{w}")
    print("校验通过：四类采集量都在可解释范围内")
    return 0


if __name__ == "__main__":
    sys.exit(main())
