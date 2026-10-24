"""麦当劳中国 MCP 客户端（零依赖，仅标准库）。

协议要点（2026-10 实测）：
- Streamable HTTP，单端点；initialize 成功后响应头带回 Mcp-Session-Id，后续请求需携带
- 响应为 JSON 或 SSE（data: 行），notification 类消息返回 202 空 body
- 工具返回的 text = 官方 prompt 指引 + 内嵌业务 JSON（从首个 {"success" 起，用 raw_decode 截取）
- 限流 600 次/分钟/Token，429 时指数退避重试
- 价格口径：query-meals 的 currentPrice 单位为元（字符串）；calculate-price 与
  modification.price 单位为分（整数）
"""
import json
import os
import re
import time
import urllib.error
import urllib.request

DEFAULT_URL = "https://mcp.mcd.cn/mcp-servers/mcd-mcp"


class McpError(RuntimeError):
    pass


class McpClient:
    def __init__(self, token=None, url=None):
        self.token = token or os.environ.get("MCD_MCP_TOKEN")
        if not self.token:
            raise McpError("缺少 MCD_MCP_TOKEN（在 https://open.mcd.cn/mcp 控制台申请）")
        self.url = url or os.environ.get("MCD_MCP_URL", DEFAULT_URL)
        self.session_id = None
        self._id = 0
        info = self._rpc("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "mcd-research-lab", "version": "0.1.0"},
        })
        if "error" in info:
            raise McpError(f"initialize 失败: {info['error']}")
        self._rpc("notifications/initialized", notify=True)

    def _headers(self):
        h = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": f"Bearer {self.token}",
        }
        if self.session_id:
            h["Mcp-Session-Id"] = self.session_id
        return h

    def _rpc(self, method, params=None, notify=False):
        body = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            body["params"] = params
        if not notify:
            self._id += 1
            body["id"] = self._id
        raw = ""
        for attempt in range(5):
            try:
                req = urllib.request.Request(
                    self.url, data=json.dumps(body).encode("utf-8"),
                    headers=self._headers())
                with urllib.request.urlopen(req, timeout=60) as r:
                    if self.session_id is None:
                        self.session_id = r.headers.get("Mcp-Session-Id")
                    raw = r.read().decode("utf-8")
                break
            except urllib.error.HTTPError as e:
                if e.code in (429, 500, 502, 503) and attempt < 4:
                    time.sleep(2 ** attempt)
                    continue
                raise McpError(f"{method} HTTP {e.code}: {e.read().decode('utf-8')[:200]}")
        if not raw.strip():
            return {}
        for line in raw.splitlines():
            if line.startswith("data:"):
                try:
                    return json.loads(line[5:].strip())
                except json.JSONDecodeError:
                    continue
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"error": {"message": raw[:200]}}

    def call(self, name, **arguments):
        """调用工具，返回原始 text（可能含 prompt 指引 + 内嵌 JSON）。"""
        r = self._rpc("tools/call", {"name": name, "arguments": arguments})
        if "error" in r:
            raise McpError(f"{name}: {r['error'].get('message', r['error'])}")
        result = r.get("result", {})
        if result.get("isError"):
            raise McpError(f"{name}: {result}")
        return "".join(c.get("text", "") for c in result.get("content", [])
                       if c.get("type") == "text")

    def call_json(self, name, **arguments):
        """调用工具并提取内嵌业务 JSON。"""
        text = self.call(name, **arguments)
        m = re.search(r'\{"success"', text)
        if not m:
            raise McpError(f"{name}: 未找到 JSON 载荷: {text[:120]}")
        obj, _ = json.JSONDecoder().raw_decode(text[m.start():])
        if not obj.get("success", True):
            raise McpError(f"{name}: {obj.get('message', obj)}")
        return obj

    # ---- 常用封装 ----

    def menu(self, store_code):
        j = self.call_json("query-meals", storeCode=store_code,
                           orderType=1, beType=1)
        d = j["data"]
        return d["categories"], d["meals"]

    def meal_detail(self, store_code, code):
        j = self.call_json("query-meal-detail", storeCode=store_code,
                           orderType=1, beType=1, code=code)
        return j.get("data") or {}

    def calculate_price(self, store_code, items):
        """items: [{productCode, quantity, ...}]，返回价格单位为分。"""
        j = self.call_json("calculate-price", storeCode=store_code,
                           orderType=1, beType=1, items=items)
        return j.get("data") or {}

    def nearby_store(self, city, keyword):
        text = self.call("query-nearby-stores", beType=1, searchType=2,
                         city=city, keyword=keyword)
        m = re.search(r'\{"success"', text)
        obj, _ = json.JSONDecoder().raw_decode(text[m.start():])
        return obj["data"][0] if obj.get("data") else {}
