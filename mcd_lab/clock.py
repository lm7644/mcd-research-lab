"""统一时钟：日期/时间戳一律按北京时间（UTC+8）生成。

GitHub Actions runner 的本地时区是 UTC，裸 ``datetime.now()`` 会比北京日期晚一天，
导致北京时间凌晨的运行把数据写进前一日的快照。所有模块统一走这里，
优先用 MCP ``now-time-info`` 返回的 serverTime 定日期。
"""
import datetime as dt

BEIJING = dt.timezone(dt.timedelta(hours=8))


def parse_server_time(value):
    """serverTime（如 ``2026-11-05T10:42:06.771``，无时区）→ 北京时间 datetime。"""
    if not value:
        return None
    try:
        t = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t.replace(tzinfo=BEIJING) if t.tzinfo is None else t.astimezone(BEIJING)


def now():
    return dt.datetime.now(BEIJING)


def today(server_time=None):
    return (parse_server_time(server_time) or now()).date()


def stamp(server_time=None):
    return (parse_server_time(server_time) or now()).isoformat(timespec="seconds")
