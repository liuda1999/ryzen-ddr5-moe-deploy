# -*- coding: utf-8 -*-
"""补充密钥机制与安装路径说明。"""
import io

NOTE = """  密钥机制与安装路径（实测结论）：
    api-key.txt 支持多行，每行一个密钥（井号开头是注释），脚本会把它们用逗号
    拼接后以 --api-key 传值给服务，因此项目可以放在含中文的目录下。
    之所以不用 llama-server 的 --api-key-file：实测该参数打不开含中文的路径
    （报 failed to open file），而 --model 用同样的中文路径却正常，属该参数自身限制。
    建议：虽已验证中文路径可用，仍推荐装到纯英文路径，避免个别工具的编码坑。

"""

# ---- 部署说明 ----
D = r"E:\llm-cpp\部署说明.txt"
t = io.open(D, encoding='utf-8').read()
anchor = "  重新编译（你本机，Visual Studio 生成器）："
if '密钥机制与安装路径' not in t:
    assert anchor in t
    t = t.replace(anchor, NOTE + anchor, 1)
    io.open(D, 'w', encoding='utf-8', newline='\r\n').write(t)
    print('部署说明已更新')
else:
    print('部署说明已含该说明')

# ---- 手册 ----
M = r"E:\llm-cpp\参数阶梯手册.md"
s = io.open(M, encoding='utf-8').read()
anchor2 = "- **首次开放要放行防火墙**"
if '--api-key-file' not in s:
    add = ("> 实现细节：密钥由脚本读出后以 `--api-key` 传值给服务（不是 `--api-key-file`）。\n"
           "> 实测 llama-server 的 `--api-key-file` 打不开含中文的路径，而 `--model` 用同样\n"
           "> 的中文路径却正常，属该参数自身限制，因此绕开它。项目可放在含中文的目录，\n"
           "> 但仍推荐纯英文路径。\n\n")
    assert anchor2 in s
    s = s.replace(anchor2, add + anchor2, 1)
    io.open(M, 'w', encoding='utf-8', newline='\r\n').write(s)
    print('手册已更新')
else:
    print('手册已含该说明')
