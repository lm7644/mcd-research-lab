# 麦麦研究所 · mcd-research-lab

> 给麦当劳菜单建了个研究所：**行情部**每天出《麦麦行情日报》，**考古部**挖出每款套餐的隐藏吃法，**积分理财科**告诉你积分怎么换最划算。
> 全部数据来自麦当劳中国官方 MCP 实时接口，零依赖（纯 Python 标准库），GitHub Action 每日自动更新。

![Python](https://img.shields.io/badge/python-3.8%2B-blue) ![Dependencies](https://img.shields.io/badge/dependencies-0-brightgreen) ![Data](https://img.shields.io/badge/data-官方MCP实时-success) ![Update](https://img.shields.io/badge/更新-每日自动-orange)

**🖥️ 在线演示**：开启 GitHub Pages（Settings → Pages → 分支 `main`、目录 `/docs`）后访问
`https://<你的用户名>.github.io/mcd-research-lab/` —— 今日行情 / 省钱榜 / 自由度榜一页看全。

麦当劳程序员创意开发大赛参赛作品 · 非麦当劳官方产品

---

## 📈 今日行情

<!-- MARKET:BEGIN -->
> 数据来源：麦当劳中国官方 MCP 实时接口 · 门店 1450713 · 在售 91 项。本日报由 GitHub Action 自动生成，历史报告见本目录。

## 🔺 涨价 / 🔻 降价

今日价格无变动，麦门平稳。

## 🆕 上新
- **满分厚松饼堡双人餐** ¥39.9

## 📅 活动日历变动
- 🆕 2026年10月30日 往期回顾 麦当劳「我就喜欢」限定丝巾正式开售🔥
- 🆕 2026年10月31日 今日 麦当劳「我就喜欢」限定丝巾正式开售🔥
- 🆕 2026年10月31日 今日 麦当劳 X PEACEMINUSONE
- 🆕 2026年10月31日 今日 早餐爆款回归，快来pick你的厚松饼堡！📣
- 🆕 2026年10月31日 今日 麦当劳联动G-DRAGON
- 🆕 2026年10月31日 今日 韩式风味蘸酱上新❤️就「酱」心有所「薯」
- 🆕 2026年10月31日 今日 🫐一口爆汁！蓝莓爆爆珠麦旋风上新
- 🆕 2026年10月31日 今日 🍫麦咖啡13.9r浓浓黑巧来啦！
<!-- MARKET:END -->

完整日报见 [`docs/market/`](docs/market/)，每日快照数据见 [`data/snapshots/`](data/snapshots/)。

## 🏛️ 三个科室

### 📈 行情部 —— 《麦麦行情日报》
每天早上 06:30，GitHub Action 拉取官方菜单/券池/活动日历，与昨日快照对比，自动出刊：
涨价 🔺 / 降价 🔻 / 上新 🆕 / 下架 💀 / 券池更替 🎟️ / 活动增删 📅。
麦当劳菜单第一次变成了可以「看盘」的行情数据。

### ⛏️ 考古部 —— 隐藏吃法图鉴
官方点餐接口里，每个套餐都是一棵组合树：主食轮 × 小食轮 × 饮料轮，选项可替换，还藏着**特调**（加酱、加吉士、去冰、换燕麦奶……多数 0 元）。
考古部把全部有选配空间的套餐组合树挖出存档，每日随菜单自动更新（完整清单与实数见摘要）：
- [考古发现摘要（自由度排行榜 + 全场 0 元特调清单）](docs/archaeology/INDEX.md)
- 单品图鉴示例：[巨无霸三件套](docs/archaeology/巨无霸三件套.md)（12 项免费特调、12 个替换位、组合树 34 节点）
- 原始数据：[`data/archaeology.json`](data/archaeology.json)

### 💰 积分理财科 —— 积分省钱榜
积分商城的兑换券大多是「积分 + 现金」形式。本科室把它和菜单现价做联表，算出**每万积分到底省多少钱**：
- [今日省钱榜](docs/market/)（每日更新，文件名带日期）—— 实测发现：500 积分换「22.9 元 2 份板烧鸡腿堡」每万积分省 ¥482，是同档巨无霸组合的 10 倍
- 🧸 积分周边墙：6666 分的罗技键鼠套装、8888 分的 Nike 联名鞋都在积分商城目录里
- `python -m mcd_lab.points --me`：生成**个人积分体检报告**（余额 / 本月将过期积分 / 抽奖还是兑换），仅本地运行

## 🚀 快速开始

```bash
export MCD_MCP_TOKEN=你的Token    # 在 https://open.mcd.cn/mcp 控制台申请
python -m mcd_lab.snapshot         # 采集当日快照
python -m mcd_lab.diff             # 生成行情日报
python -m mcd_lab.points           # 积分省钱榜
python -m mcd_lab.archaeology --limit 80   # 组合空间考古
python -m mcd_lab.points --me      # 个人积分体检（可选）
```

MCP 连接配置见 [`mcp-config.example.json`](mcp-config.example.json)（仅含 `${MCD_MCP_TOKEN}` 占位符，仓库内无真实凭证）。

## 🎯 目标用户

- 天天点麦麦、想知道「今天什么变了/怎么点最值」的打工人
- 攒了一堆积分、不知道换什么划算的麦当劳会员
- 好奇「麦当劳隐藏吃法」的麦门信徒
- 想学习 MCP / Streamable HTTP / GitHub Action 数据管道的开发者（本项目全流程零依赖可复用）

## 🗂️ 仓库结构

```
mcd_lab/          采集·分析·渲染（纯标准库）
  client.py       MCP Streamable HTTP 客户端（会话/429退避/JSON提取）
  snapshot.py     每日快照采集
  diff.py         差异引擎 + 日报 + README行情区块重写
  points.py       积分省钱榜 / 个人体检
  archaeology.py  组合空间枚举器
data/             快照与结构化结果（数据即内容）
docs/             在线演示（index.html）+ 行情日报 + 图鉴 + 稳定名数据接口
.github/          每日自动化 workflow
```

## ⚖️ 说明

- 本项目为「麦当劳程序员创意开发大赛」参赛作品，非麦当劳官方产品；
- 全部数据来自麦当劳中国官方 MCP 只读接口，本项目不自动领券、不下单、不消耗积分；
- 个人体检（`--me`）模式仅在用户本地运行，报告不进入仓库；
- 价格与商品以门店实际供应为准，榜单结论仅供参考。

## 📄 参赛文件

- [CONTEST_DECLARATION.md](CONTEST_DECLARATION.md) · 参赛声明（官方模板原文）
- [MCP_INTEGRATION.md](MCP_INTEGRATION.md) · MCP 集成说明（真实调用链）

## License

MIT
