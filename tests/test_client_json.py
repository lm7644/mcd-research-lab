"""mcd_lab.client 内嵌 JSON 提取（raw_decode）单测。

被测契约（client.py 模块 docstring 原文）：
「工具返回的 text = 官方 prompt 指引 + 内嵌业务 JSON
（从首个 {"success" 起，用 raw_decode 截取）」

全部用例经 ScriptedHTTP 模拟传输层，无真实网络请求。
"""
import json
import os
import unittest
from unittest import mock

from mcd_lab.client import McpClient, McpError

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

# ---- 夹具：官方 prompt 指引 + 内嵌业务 JSON（字段形状对齐真实快照） ----

PROMPT = ("以下是门店 1450713 的在售餐品（数据来自麦当劳官方接口）：\n"
          "提示：currentPrice 单位为元；如遇售罄以下单页为准。\n")

PAYLOAD = json.dumps({
    "success": True,
    "data": {
        "categories": [{"name": "人气热卖",
                        "meals": [{"code": "9900005456", "tags": ["浓郁奶香"]}]}],
        "meals": {"9900005456": {"name": "麦辣鸡腿汉堡三件套",
                                 "currentPrice": "33.5",
                                 "originalPrice": "46",
                                 "canWithOrder": False}},
    },
}, ensure_ascii=False)


class ClientJsonExtractionTest(unittest.TestCase):
    """call_json / call / nearby_store / menu / meal_detail 的提取与拼装行为。"""

    def setUp(self):
        env_patch = mock.patch.dict(os.environ)
        env_patch.start()
        os.environ.pop("MCD_MCP_TOKEN", None)
        os.environ.pop("MCD_MCP_URL", None)
        self.addCleanup(env_patch.stop)
        sleep_patch = mock.patch("time.sleep")
        self.sleep = sleep_patch.start()
        self.addCleanup(sleep_patch.stop)
        self.http = ScriptedHTTP([INIT_OK, NOTIFY_202])
        http_patch = mock.patch("urllib.request.urlopen", new=self.http)
        http_patch.start()
        self.addCleanup(http_patch.stop)
        self.client = McpClient(token="test-token")

    # ---- 内嵌 JSON 提取（raw_decode） ----

    def test_prompt_plus_payload(self):
        self.http.queue(rpc_result(PROMPT + PAYLOAD + "\n以上为实时数据。"))
        obj = self.client.call_json("query-meals", storeCode="1450713",
                                    orderType=1, beType=1)
        self.assertTrue(obj["success"])
        meal = obj["data"]["meals"]["9900005456"]
        self.assertEqual(meal["name"], "麦辣鸡腿汉堡三件套")
        self.assertEqual(meal["currentPrice"], "33.5")

    def test_raw_decode_stops_at_object_boundary(self):
        # 对象之后还有 prompt 尾注且含未闭合花括号：raw_decode 必须干净截断，
        # 不会被尾注的「{」带偏（正则 .* 贪婪匹配会在这里出错）
        tail = "\n尾注：套餐组合如 {主食 小食 饮料 可选，价格以\n"
        self.http.queue(rpc_result(PROMPT + PAYLOAD + tail))
        obj = self.client.call_json("query-meals", storeCode="1450713")
        self.assertEqual(obj["data"]["meals"]["9900005456"]["name"],
                         "麦辣鸡腿汉堡三件套")

    def test_braces_inside_string_values(self):
        payload = json.dumps({"success": True, "data": {
            "name": "麦辣鸡翅{超值}双人餐", "note": "含 \"辣翅\" 两份"}},
            ensure_ascii=False)
        self.http.queue(rpc_result(PROMPT + payload + " 尾注 }"))
        obj = self.client.call_json("query-meals", storeCode="1450713")
        self.assertEqual(obj["data"]["name"], "麦辣鸡翅{超值}双人餐")
        self.assertEqual(obj["data"]["note"], "含 \"辣翅\" 两份")

    def test_first_marker_wins(self):
        # 锁定「首个 {"success"」口径：先出现的标记对象即为载荷
        decoy = '{"success":true,"tag":"decoy"}'
        self.http.queue(rpc_result(decoy + "\n" + PROMPT + PAYLOAD))
        obj = self.client.call_json("query-meals", storeCode="1450713")
        self.assertEqual(obj["tag"], "decoy")

    def test_missing_marker_raises(self):
        self.http.queue(rpc_result(PROMPT + "服务器开小差了，请稍后再试。"))
        with self.assertRaisesRegex(McpError, "未找到 JSON 载荷"):
            self.client.call_json("query-meals", storeCode="1450713")

    def test_marker_must_be_tightly_braced(self):
        # 标记正则锁定 \\{"success"：花括号后带空格即不匹配（既定口径，防止误捕）
        self.http.queue(rpc_result(PROMPT + '{ "success": true, "data": {}}'))
        with self.assertRaisesRegex(McpError, "未找到 JSON 载荷"):
            self.client.call_json("query-meals", storeCode="1450713")

    def test_success_false_raises_with_message(self):
        self.http.queue(rpc_result('{"success":false,"message":"门店编码无效"}'))
        with self.assertRaisesRegex(McpError, "门店编码无效"):
            self.client.call_json("query-meals", storeCode="0000000")

    def test_success_false_without_message(self):
        self.http.queue(rpc_result('{"success":false,"code":4001}'))
        with self.assertRaises(McpError) as cm:
            self.client.call_json("query-meals", storeCode="0000000")
        self.assertIn("success", str(cm.exception))  # 无 message 时兜底输出整个对象

    # ---- call 的文本拼装与错误路径 ----

    def test_call_joins_text_blocks_only(self):
        body = json.dumps({"jsonrpc": "2.0", "id": 2, "result": {"content": [
            {"type": "text", "text": "券A"},
            {"type": "image", "data": "base64=="},
            {"type": "text", "text": "券B"},
            {"type": "text"},
        ]}}, ensure_ascii=False)
        self.http.queue(FakeResponse(body))
        self.assertEqual(self.client.call("available-coupons"), "券A券B")

    def test_call_raises_on_jsonrpc_error(self):
        body = json.dumps({"jsonrpc": "2.0", "id": 2,
                           "error": {"code": -32601, "message": "未知工具"}},
                          ensure_ascii=False)
        self.http.queue(FakeResponse(body))
        with self.assertRaisesRegex(McpError, "未知工具"):
            self.client.call("no-such-tool")

    def test_call_raises_on_is_error(self):
        body = json.dumps({"jsonrpc": "2.0", "id": 2, "result": {
            "isError": True,
            "content": [{"type": "text", "text": "storeCode 必填"}]}},
            ensure_ascii=False)
        self.http.queue(FakeResponse(body))
        with self.assertRaisesRegex(McpError, "storeCode 必填"):
            self.client.call("query-meals")

    def test_call_request_body_plumbing(self):
        self.http.queue(rpc_result(PROMPT + PAYLOAD))
        self.client.call_json("query-meals", storeCode="1450713",
                              orderType=1, beType=1)
        sent = self.http.bodies()[-1]
        self.assertEqual(sent["method"], "tools/call")
        self.assertEqual(sent["params"], {
            "name": "query-meals",
            "arguments": {"storeCode": "1450713", "orderType": 1, "beType": 1}})

    # ---- 便捷封装 ----

    def test_menu_returns_categories_and_meals(self):
        self.http.queue(rpc_result(PROMPT + PAYLOAD))
        categories, meals = self.client.menu("1450713")
        self.assertEqual(categories[0]["name"], "人气热卖")
        self.assertIn("9900005456", meals)

    def test_meal_detail_and_missing_data(self):
        detail = json.dumps({"success": True, "data": {
            "code": "9900005456", "name": "麦辣鸡腿汉堡三件套",
            "rounds": [{"name": "主食轮", "minQuantity": 1, "maxQuantity": 1,
                        "choices": [{"name": "麦辣鸡腿堡", "isDefault": 1}]}]}},
            ensure_ascii=False)
        self.http.queue(rpc_result(detail))
        got = self.client.meal_detail("1450713", "9900005456")
        self.assertEqual(got["name"], "麦辣鸡腿汉堡三件套")
        self.http.queue(rpc_result('{"success":true}'))
        self.assertEqual(self.client.meal_detail("1450713", "x"), {})

    def test_nearby_store_first_and_empty(self):
        stores = json.dumps({"success": True, "data": [
            {"storeCode": "1450713", "storeName": "丽江店"},
            {"storeCode": "1450714", "storeName": "束河店"}]}, ensure_ascii=False)
        self.http.queue(rpc_result(stores))
        first = self.client.nearby_store("丽江", "万达")
        self.assertEqual(first["storeName"], "丽江店")
        sent = self.http.bodies()[-1]["params"]["arguments"]
        self.assertEqual(sent, {"beType": 1, "searchType": 2,
                                "city": "丽江", "keyword": "万达"})
        self.http.queue(rpc_result('{"success":true,"data":[]}'))
        self.assertEqual(self.client.nearby_store("丽江", "不存在"), {})


if __name__ == "__main__":
    unittest.main()
