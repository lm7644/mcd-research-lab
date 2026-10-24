# workbuddy.md · WorkBuddy 真实使用记录

> 本文件为「麦当劳程序员创意开发大赛」WorkBuddy 专项提交材料，记录本项目对腾讯 WorkBuddy 智能体的**真实使用**过程：由项目所有者在其 WorkBuddy 账号中真实下达任务，WorkBuddy 自主完成开发，产出已合入本仓库。

## 一、使用事实

| 项 | 内容 |
|---|---|
| 使用平台 | 腾讯 WorkBuddy 桌面端（www.workbuddy.cn，腾讯系账号登录，账号信息可经腾讯侧核验） |
| 会话时间 | 2026-10-24 深夜至 10-25 凌晨（交付历时 18 分 14 秒） |
| 会话主题 | 给 McDonald's MCP 项目补自动化测试 |
| 工作目录 | 本仓库本地克隆（WorkBuddy 直接读写） |
| 官方分享链接 | https://workbuddy.link/p/OYNDcMfqOOlAQ2T1qyETML |
| 真实产出 | `tests/` 目录 4 个文件、42 个用例，commit `6a5b0d6`，本地全绿 |

## 二、任务说明（项目所有者真实下达的 prompt，原样引用）

> 请给这个 McDonald's MCP 情报项目补一套自动化测试。要求：
> 1. 只新增 tests/ 目录，不修改任何现有文件；
> 2. 纯 Python 标准库 unittest，不引入任何第三方依赖；
> 3. 对 mcd_lab/client.py 的核心逻辑做单测（内嵌 JSON 提取 raw_decode、429 指数退避、分单位换算），用 unittest.mock 模拟 HTTP 响应，绝不允许真实网络请求；
> 4. 跑通 python -m unittest discover -s tests -v 全绿后结束。

## 三、WorkBuddy 交付记录（摘自官方分享页，AI 生成内容）

**项目总监 · 已完成 18m14s · 测试套件已交付并全部验证通过**

交付物（仅新增 tests/，零修改现有文件）——项目定位在 ~/.zcode/workspace/default/mcd-research-lab（git 仓库），新增 4 个文件：

| 文件 | 用例数 | 覆盖 |
|---|---|---|
| tests/__init__.py | — | 包标记 + 发现模式约定 |
| tests/test_client_json.py | 15 | 内嵌 JSON 提取（raw_decode） |
| tests/test_client_retry.py | 17 | 429 指数退避 + 传输层协议 |
| tests/test_price_units.py | 10 | 分/元价格口径与换算 |

三大要求区的测试要点：

- raw_decode：prompt+载荷提取、对象边界干净截断（尾注含未闭合花括号）、字符串值内含花括号、首个标记锁定、标记缺失/success:false 报错、text content 拼装、isError/JSON-RPC error 路径；
- 429 退避：429 两次后成功、5 次耗尽抛错（断言 sleep 序列恰为 1,2,4,8）、500/502/503 同路径重试、404 不重试、URLError 原样抛出；
- 分单位换算：client.py 本身不做换算（只按 docstring 口径透传），换算在生产代码 archaeology.walk_modification。测试双管齐下：client 层锁定「元字符串 vs 分整数」契约 + 跨工具口径对齐（菜单 33.5 元 ≡ 试算 3350 分），并直接单测生产换算函数。

**验证证据**

- `python -m unittest discover -s tests -v` → Ran 42 tests, OK（0.02s；-t . 显式顶层模式同样全绿）；
- 变异验证 5/5 捕获：退避关闭（3 例红）、会话头丢失（2 红）、重试码收窄为仅 429（1 红）、标记正则放宽（22 红）、分换算去掉 /100（2 红）——全绿不是假象；
- 零改动证明：变异后 git checkout 恢复，client.py/archaeology.py sha256 与变异前完全一致，git status --porcelain 仅 ?? tests/。

**WorkBuddy 顺带发现的两处既有缺陷（遵守约束未修，建议后续排期）**

1. `client.nearby_store` 在无 `{"success"` 标记时会对 None 取 `.start()` 抛 TypeError；
2. `archaeology.walk_modification` 注释写「保留最大价」但实现是「保留首见」——测试已按实际实现锁定并在用例内标注，防回归时语义被悄悄改变。

## 四、项目所有者的合入验收（真实发生）

- 复跑 `python -m unittest discover -s tests`：42 用例全绿（0.008s，纯 mock 零网络）；
- `git status` 确认改动范围仅 `tests/` 新增，现有文件零修改；
- 以 commit `6a5b0d6`（test: WorkBuddy 协作产出）合入 main 并推送。

## 五、真实性与后续

- 以上对话内容摘自 WorkBuddy 官方分享页（链接见上），未增删改对话实质内容；本文件由项目所有者整理格式，事实以 WorkBuddy 平台侧账号使用数据为准。
- 本项目主体（行情部/考古部/积分理财科三个科室）由 AI 辅助在本次 WorkBuddy 会话之外完成；WorkBuddy 承担的增量开发即本文件记录的测试套件，特此如实说明。
