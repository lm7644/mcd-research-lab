"""价格单位口径单测：元（字符串）vs 分（整数）。

client.py 模块 docstring 锁定的口径：
- query-meals 的 currentPrice 单位为元（字符串）
- calculate-price 与 modification.price 单位为分（整数）

client 本身不做任何换算、原样透传；换算由调用方完成
（mcd_lab/archaeology.py 同款公式 round(int(分) / 100, 2)）。
本文件双管齐下：① 锁定 client 层的单位契约与跨工具口径对齐；
② 直接单测生产换算函数（archaeology.walk_modification / diff.yuan）。
全部用例经 ScriptedHTTP 模拟传输层，无真实网络请求。
"""
import json
import os
import unittest
from unittest import mock

from mcd_lab.archaeology import walk_modification
from mcd_lab.client import McpClient
from mcd_lab.diff import yuan

SESSION_ID = "sess-test-001"


# ---- 模拟传输层（仅标准库） ----

class FakeResponse:
    """模拟 urlopen 返回值：支持 with 语句、read() 与 headers.get()。"""

    def __init__(self, body=b"", session_id=None):
        self._body = body.encode("utf-8") if isinstance(body, str) else body
        self.headers = {"Mcp-Session-Id": session_id} if session_id else {}

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class ScriptedHTTP:
    """按脚本序列应答 urlopen，记录请求与超时；脚本耗尽即报错（防假绿）。"""

    def __init__(self, script):
        self.script = list(script)
        self.requests = []
        self.timeouts = []

    def __call__(self, req, timeout=None):
        self.requests.append(req)
        self.timeouts.append(timeout)
        if not self.script:
            raise AssertionError("脚本外的多余请求: %s" % req.full_url)
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def queue(self, *items):
        self.script.extend(items)

    def bodies(self):
        return [json.loads(r.data.decode("utf-8")) for r in self.requests]

    def headers_of(self, req):
        return {k.lower(): v for k, v in req.header_items()}


def rpc_result(text, msg_id=1):
    """tools/call 成功响应：单个 text content。"""
    return FakeResponse(json.dumps({
        "jsonrpc": "2.0", "id": msg_id,
        "result": {"content": [{"type": "text", "text": text}]},
    }, ensure_ascii=False))


INIT_OK = FakeResponse(json.dumps({
    "jsonrpc": "2.0", "id": 1,
    "result": {"protocolVersion": "2024-11-05", "capabilities": {},
               "serverInfo": {"name": "mcd-mcp", "version": "1.0"}},
}), session_id=SESSION_ID)

NOTIFY_202 = FakeResponse(b"")  # notification 类消息：202 空 body

# ---- 夹具：同一餐品在两个工具下的不同单位口径 ----

MENU_TEXT = ("以下是门店 1450713 的在售餐品：\n" + json.dumps({
    "success": True,
    "data": {"categories": [], "meals": {"9900005456": {
        "name": "麦辣鸡腿汉堡三件套", "currentPrice": "33.5",
        "originalPrice": "46", "canWithOrder": False}}},
}, ensure_ascii=False))

CALC_TEXT = ("当前购物车价格试算结果：\n" + json.dumps({
    "success": True,
    "data": {"storeCode": "1450713", "totalPrice": 3350,
             "originalPrice": 4600,
             "items": [{"productCode": "9900005456", "quantity": 1,
                        "price": 3350}]},
}, ensure_ascii=False))

DETAIL_TEXT = ("餐品详情：\n" + json.dumps({
    "success": True,
    "data": {"code": "9900005456", "name": "麦辣鸡腿汉堡三件套",
             "rounds": [{"name": "特调轮", "choices": [{
                 "name": "麦辣鸡腿堡", "isDefault": 1,
                 "modification": {"items": [{"values": [
                     {"name": "加辣", "price": 200, "maxQuantity": 2},
                     {"name": "去冰", "price": 0, "maxQuantity": 1},
                     {"name": "换燕麦奶", "price": None, "maxQuantity": 1}]}]}}]}]},
}, ensure_ascii=False))


def fen_to_yuan(fen):
    """调用方换算公式（archaeology.walk_modification 同款）：分 -> 元。"""
    return round(int(fen) / 100, 2)


class PriceUnitContractTest(unittest.TestCase):
    """client 层口径：分原样透传、元字符串原样透传、跨工具口径对齐。"""

    def setUp(self):
        env_patch = mock.patch.dict(os.environ)
        env_patch.start()
        os.environ.pop("MCD_MCP_TOKEN", None)
        os.environ.pop("MCD_MCP_URL", None)
        self.addCleanup(env_patch.stop)
        sleep_patch = mock.patch("time.sleep")
        sleep_patch.start()
        self.addCleanup(sleep_patch.stop)
        self.http = ScriptedHTTP([INIT_OK, NOTIFY_202])
        http_patch = mock.patch("urllib.request.urlopen", new=self.http)
        http_patch.start()
        self.addCleanup(http_patch.stop)
        self.client = McpClient(token="test-token")

    def test_calculate_price_returns_fen_verbatim(self):
        self.http.queue(rpc_result(CALC_TEXT))
        data = self.client.calculate_price(
            "1450713", [{"productCode": "9900005456", "quantity": 1}])
        # 客户端不做换算：totalPrice 仍是「分」单位的整数
        self.assertIsInstance(data["totalPrice"], int)
        self.assertEqual(data["totalPrice"], 3350)
        self.assertEqual(data["totalPrice"] / 100, 33.5)
        sent = self.http.bodies()[-1]["params"]
        self.assertEqual(sent["name"], "calculate-price")
        self.assertEqual(sent["arguments"]["storeCode"], "1450713")
        self.assertEqual(sent["arguments"]["items"],
                         [{"productCode": "9900005456", "quantity": 1}])

    def test_calculate_price_missing_data(self):
        self.http.queue(rpc_result('{"success":true}'))
        self.assertEqual(self.client.calculate_price("1450713", []), {})

    def test_menu_price_is_yuan_string(self):
        self.http.queue(rpc_result(MENU_TEXT))
        _, meals = self.client.menu("1450713")
        price = meals["9900005456"]["currentPrice"]
        self.assertIsInstance(price, str)      # 元：字符串
        self.assertEqual(float(price), 33.5)   # 直接 float，不除 100

    def test_cross_tool_unit_alignment(self):
        # 同一餐品：菜单口价 33.5 元（字符串），试算口价 3350 分（整数）
        self.http.queue(rpc_result(MENU_TEXT))
        _, meals = self.client.menu("1450713")
        self.http.queue(rpc_result(CALC_TEXT))
        data = self.client.calculate_price(
            "1450713", [{"productCode": "9900005456", "quantity": 1}])
        menu_yuan = float(meals["9900005456"]["currentPrice"])
        calc_yuan = fen_to_yuan(data["totalPrice"])
        self.assertEqual(menu_yuan, calc_yuan)
        self.assertEqual(calc_yuan, 33.5)

    def test_meal_detail_modification_price_in_fen(self):
        self.http.queue(rpc_result(DETAIL_TEXT))
        detail = self.client.meal_detail("1450713", "9900005456")
        mod = detail["rounds"][0]["choices"][0]["modification"]
        prices = {v["name"]: v["price"]
                  for it in mod["items"] for v in it["values"]}
        self.assertEqual(prices["加辣"], 200)          # 分：整数
        self.assertEqual(prices["去冰"], 0)            # 分：整数
        self.assertIsNone(prices["换燕麦奶"])           # 缺失价的原始形态
        self.assertEqual(fen_to_yuan(prices["加辣"]), 2.0)


class FenYuanConversionTest(unittest.TestCase):
    """生产换算函数：archaeology.walk_modification（分->元）与 diff.yuan（元字符串->float）。"""

    def test_walk_modification_converts_fen_to_yuan(self):
        mod = {"items": [{"values": [
            {"name": "加辣", "price": 200, "maxQuantity": 2},
            {"name": "加芝士", "price": 350, "maxQuantity": 1},
            {"name": "去冰", "price": 0, "maxQuantity": 1},
            {"name": "换燕麦奶", "price": None, "maxQuantity": 1},
        ]}]}
        out = walk_modification(mod)
        got = {m["name"]: (m["price"], m["max"]) for m in out}
        self.assertEqual(got, {
            "加辣": (2.0, 2), "加芝士": (3.5, 1),
            "去冰": (0.0, 1), "换燕麦奶": (0.0, 1)})

    def test_walk_modification_dedup_keeps_first_seen(self):
        # 注意：源码注释写「保留最大价」，实现实为「保留首见」——
        # 本测试按实际实现锁定现状，防回归时悄悄改变合并语义
        mod = {"items": [{"values": [
            {"name": "加辣", "price": 200, "maxQuantity": 2},
            {"name": "加辣", "price": 999, "maxQuantity": 1},
        ]}]}
        got = {m["name"]: (m["price"], m["max"]) for m in walk_modification(mod)}
        self.assertEqual(got, {"加辣": (2.0, 2)})

    def test_walk_modification_empty(self):
        self.assertEqual(walk_modification(None), [])
        self.assertEqual(walk_modification({}), [])

    def test_fen_to_yuan_table(self):
        cases = [(0, 0.0), (1, 0.01), (5, 0.05), (99, 0.99), (100, 1.0),
                 (199, 1.99), (3350, 33.5), (4750, 47.5), (999999, 9999.99)]
        for fen, expected in cases:
            with self.subTest(fen=fen):
                self.assertEqual(fen_to_yuan(fen), expected)

    def test_yuan_parses_string_prices(self):
        self.assertEqual(yuan("33.5"), 33.5)
        self.assertEqual(yuan("46"), 46.0)
        self.assertEqual(yuan(33.5), 33.5)    # 容错：数字也收
        self.assertIsNone(yuan(None))         # 容错：缺失 -> None
        self.assertIsNone(yuan(""))           # 容错：空串 -> None
        self.assertIsNone(yuan("暂缺"))        # 容错：非数字 -> None


if __name__ == "__main__":
    unittest.main()
