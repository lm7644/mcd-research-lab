"""数据完整性校验：对比最近两份快照，四类采集量分别判断「采集不全 / 真实变动」。

晚于 / 早于营业时段、整类缺失、某类归零 —— 视为采集不全，直接中止（退出码 1），
校验通过前不会进入发布步骤，因此不会把残缺快照提交上线。

用法：python -m mcd_lab.validate
"""
import json
import sys
from pathlib import Path

from . import clock

ROOT = Path(__file__).resolve().parent.parent

# 类别 → (快照字段, 允许的相对下降阈值, 中文名)
CATS = [
    ("meals", "meals", 0.10, "菜单"),
    ("coupons", "couponPool", 0.30, "券池"),
    ("points", "pointsProducts", 0.20, "积分商品"),
    ("calendar", "campaignCalendar", 0.30, "活动日历"),
]
OPEN_HOUR, CLOSE_HOUR = 7, 22  # 营业时段（北京时间）


def cat_names(snap):
    return [c.get("name") for c in snap.get("categories") or [] if isinstance(c, dict)]


def main():
    files = sorted((ROOT / "data" / "snapshots").glob("*.json"))
    if len(files) < 2:
        print("只有一份快照，跳过校验")
        return 0
    prev = json.loads(files[-2].read_text(encoding="utf-8"))
    cur = json.loads(files[-1].read_text(encoding="utf-8"))

    hour = clock.parse_server_time(cur.get("serverTime"))
    off_hours = hour is not None and not (OPEN_HOUR <= hour.hour < CLOSE_HOUR)
    missing_cats = [c for c in cat_names(prev) if c not in cat_names(cur)]

    incomplete, warnings = [], []
    if off_hours:
        incomplete.append(f"采集时段异常：{hour:%H:%M}（营业时段 {OPEN_HOUR:02d}:00–{CLOSE_HOUR:02d}:00 之外）")
    if missing_cats:
        incomplete.append(f"分类整体缺失 {len(missing_cats)} 个：" + "、".join(c.replace("\n", "") for c in missing_cats))

    print(f"对比：{files[-2].name} → {files[-1].name}（serverTime={hour or '缺失'}）")
    print(f"{'类别':<6}{'上一份':>6}{'本次':>6}{'变化':>9}  判定")
    for _, key, threshold, cn in CATS:
        p = len(prev.get(key) or [])
        c = len(cur.get(key) or [])
        pct = 0.0 if not p else (c - p) / p
        if p >= 5 and c == 0:
            verdict = "采集不全（整类归零）"
            incomplete.append(f"{cn} {p} → 0")
        elif -pct > threshold:
            if off_hours:
                verdict = "采集不全（时段外骤降）"
                incomplete.append(f"{cn} {p} → {c}（{pct:+.1%}，营业时段外）")
            else:
                verdict = f"真实变动（超过告警线 {threshold:.0%}）"
                warnings.append(f"{cn} {p} → {c}（{pct:+.1%}）")
        else:
            verdict = "正常"
        print(f"{cn:<6}{p:>8}{c:>8}{pct:>+9.1%}  {verdict}")

    if incomplete:
        print("::error::采集不全，已中止发布：" + "；".join(incomplete))
        return 1
    for w in warnings:
        print(f"::warning::单类异常下降但无采集不全信号，按真实变动放行：{w}")
    print("校验通过：四类采集量都在可解释范围内")
    return 0


if __name__ == "__main__":
    sys.exit(main())
