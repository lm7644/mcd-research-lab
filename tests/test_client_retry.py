"""mcd_lab.client 传输层单测：429/5xx 指数退避、会话头、SSE、通知与错误路径。

被测契约（client.py 模块 docstring 原文）：
- Streamable HTTP 单端点；initialize 成功后响应头带回 Mcp-Session-Id，后续请求需携带
- 响应为 JSON 或 SSE（data: 行），notification 类消息返回 202 空 body
- 限流 600 次/分钟/Token，429 时指数退避重试（500/502/503 同路径）

全部用例以 unittest.mock 替换 urllib.request.urlopen 与 time.sleep：
无真实网络请求、无真实退避等待。
"""
import io
import json
import os
import unittest
import urllib.error
from unittest import mock

from mcd_lab.client import DEFAULT_URL, McpClient, McpError

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


def http_error(code, body=b'{"error":"busy"}'):
    """构造 urllib.error.HTTPError（状态码 + 可读 body）。"""
    return urllib.error.HTTPError(
        "https://mcp.mcd.cn/mcp-servers/mcd-mcp", code, "HTTP %d" % code, {},
        io.BytesIO(body))


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

PAYLOAD = json.dumps({"success": True, "data": {"ok": 1}}, ensure_ascii=False)
SSE_PROMPT = "官方 prompt 指引：\n"


class _ClientTestBase(unittest.TestCase):
    """公共 setUp：环境隔离 + urlopen/sleep 全模拟 + 已完成 initialize 的客户端。"""

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
        self.base = len(self.http.requests)  # initialize + initialized 已发生


class RetryBackoffTest(_ClientTestBase):
    """429/500/502/503 指数退避重试（time.sleep 已模拟，断言退避序列）。"""

    def test_429_retries_then_succeeds(self):
        self.http.queue(http_error(429), http_error(429), rpc_result(PAYLOAD))
        obj = self.client.call_json("query-meals", storeCode="1450713")
        self.assertEqual(obj["data"], {"ok": 1})
        self.assertEqual(self.sleep.call_args_list, [mock.call(1), mock.call(2)])
        self.assertEqual(len(self.http.requests) - self.base, 3)

    def test_429_exhausted_raises(self):
        self.http.queue(*[http_error(429) for _ in range(5)])
        with self.assertRaisesRegex(McpError, "HTTP 429"):
            self.client.call_json("query-meals", storeCode="1450713")
        self.assertEqual(self.sleep.call_args_list,
                         [mock.call(1), mock.call(2), mock.call(4), mock.call(8)])
        self.assertEqual(len(self.http.requests) - self.base, 5)

    def test_server_errors_also_retried(self):
        for code in (500, 502, 503):
            with self.subTest(code=code):
                self.sleep.reset_mock()
                before = len(self.http.requests)
                self.http.queue(http_error(code), rpc_result(PAYLOAD))
                obj = self.client.call_json("query-meals", storeCode="1450713")
                self.assertEqual(obj["data"], {"ok": 1})
                self.assertEqual(self.sleep.call_args_list, [mock.call(1)])
                self.assertEqual(len(self.http.requests) - before, 2)

    def test_404_not_retried(self):
        self.http.queue(http_error(404, body=b'{"error":"not found"}'))
        with self.assertRaisesRegex(McpError, "HTTP 404"):
            self.client.call_json("query-meals", storeCode="1450713")
        self.sleep.assert_not_called()
        self.assertEqual(len(self.http.requests) - self.base, 1)

    def test_url_error_propagates_unwrapped(self):
        # 非 HTTPError 的 URLError 不走退避分支，按原样抛出（既定行为）
        self.http.queue(urllib.error.URLError("connection refused"))
        with self.assertRaises(urllib.error.URLError):
            self.client.call_json("query-meals", storeCode="1450713")
        self.sleep.assert_not_called()
        self.assertEqual(len(self.http.requests) - self.base, 1)


class SessionAndTransportTest(_ClientTestBase):
    """会话头传播、SSE 解析、通知空 body、JSON-RPC 协议细节。"""

    def test_session_id_captured_and_forwarded(self):
        # initialize 时尚未持有会话：首请求不应带会话头，但必须带鉴权头
        first = self.http.headers_of(self.http.requests[0])
        self.assertNotIn("mcp-session-id", first)
        self.assertEqual(first["authorization"], "Bearer test-token")
        # initialize 响应头带回会话 id，后续每个请求都必须携带
        for req in self.http.requests[1:]:
            self.assertEqual(self.http.headers_of(req)["mcp-session-id"],
                             SESSION_ID)

    def test_new_request_carries_session_header(self):
        self.http.queue(rpc_result(PAYLOAD))
        self.client.call_json("query-meals", storeCode="1450713")
        last = self.http.headers_of(self.http.requests[-1])
        self.assertEqual(last["mcp-session-id"], SESSION_ID)
        self.assertEqual(last["content-type"], "application/json")
        self.assertIn("text/event-stream", last["accept"])

    def test_sse_data_line_parsed(self):
        payload = json.dumps({"jsonrpc": "2.0", "id": 2, "result": {
            "content": [{"type": "text", "text": SSE_PROMPT + PAYLOAD}]}},
            ensure_ascii=False)
        self.http.queue(FakeResponse("event: message\ndata: %s\n\n" % payload))
        obj = self.client.call_json("query-meals", storeCode="1450713")
        self.assertEqual(obj["data"], {"ok": 1})

    def test_sse_skips_unparsable_data_lines(self):
        good = json.dumps({"jsonrpc": "2.0", "id": 2, "result": {
            "content": [{"type": "text", "text": PAYLOAD}]}}, ensure_ascii=False)
        self.http.queue(FakeResponse(
            "event: message\ndata: not-json\n\ndata: %s\n\n" % good))
        obj = self.client.call_json("query-meals", storeCode="1450713")
        self.assertEqual(obj["data"], {"ok": 1})

    def test_empty_body_returns_empty_dict(self):
        self.http.queue(FakeResponse(b""))
        self.assertEqual(
            self.client._rpc("notifications/initialized", notify=True), {})

    def test_unparsable_body_becomes_error_dict(self):
        self.http.queue(FakeResponse("<html>502 Bad Gateway</html>"))
        with self.assertRaisesRegex(McpError, "502 Bad Gateway"):
            self.client.call_json("query-meals", storeCode="1450713")

    def test_jsonrpc_id_increments_and_notify_has_none(self):
        self.http.queue(rpc_result(PAYLOAD), rpc_result(PAYLOAD, msg_id=3))
        self.client.call_json("query-meals", storeCode="1450713")
        self.client.call_json("now-time-info")
        bodies = self.http.bodies()
        self.assertEqual(bodies[0]["id"], 1)       # initialize
        self.assertNotIn("id", bodies[1])          # notification 无 id
        self.assertEqual(bodies[2]["id"], 2)       # 首个 tools/call
        self.assertEqual(bodies[3]["id"], 3)       # 自增
        self.assertEqual(bodies[2]["jsonrpc"], "2.0")

    def test_requests_are_post_with_timeout(self):
        self.http.queue(rpc_result(PAYLOAD))
        self.client.call_json("query-meals", storeCode="1450713")
        req = self.http.requests[-1]
        self.assertEqual(req.get_method(), "POST")
        self.assertEqual(req.full_url, DEFAULT_URL)
        self.assertTrue(all(t == 60 for t in self.http.timeouts))


class InitAndConfigTest(_ClientTestBase):
    """构造期行为：token 来源、URL 来源、initialize 失败。"""

    def new_client(self, token="test-token", url=None):
        self.http.queue(INIT_OK, NOTIFY_202)
        return McpClient(token=token, url=url)

    def test_missing_token_raises(self):
        before = len(self.http.requests)
        with self.assertRaisesRegex(McpError, "缺少 MCD_MCP_TOKEN"):
            McpClient()
        self.assertEqual(len(self.http.requests), before)  # 未发起任何新请求

    def test_token_from_env(self):
        with mock.patch.dict(os.environ, {"MCD_MCP_TOKEN": "env-token"}):
            base = len(self.http.requests)
            client = self.new_client(token=None)
        self.assertEqual(client.token, "env-token")
        self.assertEqual(
            self.http.headers_of(self.http.requests[base])["authorization"],
            "Bearer env-token")

    def test_url_default_and_env(self):
        with mock.patch.dict(os.environ, {"MCD_MCP_URL": "https://env.test/mcp"}):
            client = self.new_client()
        self.assertEqual(client.url, "https://env.test/mcp")
        with mock.patch.dict(os.environ):
            os.environ.pop("MCD_MCP_URL", None)
            self.assertEqual(self.new_client().url, DEFAULT_URL)

    def test_initialize_error_raises(self):
        self.http.queue(FakeResponse(json.dumps({
            "jsonrpc": "2.0", "id": 1,
            "error": {"code": -32000, "message": "token 无效"}})))
        with self.assertRaisesRegex(McpError, "initialize 失败"):
            McpClient(token="bad-token")


if __name__ == "__main__":
    unittest.main()
