"""mcd-research-lab 测试包（纯 Python 标准库 unittest，零第三方依赖）。

发现模式约定：仓库根目录执行
    python -m unittest discover -s tests -v
所有用例均以 unittest.mock 替换 urllib.request.urlopen 与 time.sleep，
绝不发起真实网络请求、绝不产生真实退避等待。
"""
