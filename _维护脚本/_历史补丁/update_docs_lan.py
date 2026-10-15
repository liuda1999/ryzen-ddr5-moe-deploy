# -*- coding: utf-8 -*-
"""把局域网访问说明补进 参数阶梯手册.md 与 部署说明.txt。"""
import io

# ---------- 1) 参数阶梯手册 ----------
M = r"E:\llm-cpp\参数阶梯手册.md"
s = io.open(M, encoding='utf-8').read()

LAN_SEC = """
### 局域网访问（可选）

服务默认绑定 `0.0.0.0`，同网段的手机 / 笔记本 / 其它电脑可直接调用：

- **入口**：`http://<本机IP>:35035`（本机当前是 `http://192.168.0.100:35035`）
- **必须带密钥**：密钥在首次启动时自动生成到 `E:\\llm-cpp\\api-key.txt`，
  请求头加 `Authorization: Bearer <密钥>`，缺失会返回 `401`。
  （`/health` 不需要密钥，仅用于存活探测。）
- **首次开放要放行防火墙**：右键 `开放局域网端口.bat` → 以管理员身份运行 → 选 1。
- **想改回"仅本机"**：把 `启动大模型.bat` 顶部 `set "HOST=0.0.0.0"` 改回 `127.0.0.1`，
  并重启服务。

> 提醒：开放后，同网段任何拿到密钥的设备都能占用本机 CPU 与内存做推理，
> 不要在不可信的 Wi-Fi 环境下长期开着。
"""

anchor = "服务端口固定为 **35035**"
idx = s.find(anchor)
assert idx > 0, 'anchor not found'
# 插入到该段落结束（下一个空行+分隔线）之前
tail = s.find("\n---\n", idx)
assert tail > 0
s = s[:tail] + "\n" + LAN_SEC + s[tail:]
io.open(M, 'w', encoding='utf-8', newline='\r\n').write(s)
print('手册已更新')

# ---------- 2) 部署说明 ----------
D = r"E:\llm-cpp\部署说明.txt"
t = io.open(D, encoding='utf-8').read()

LAN_TXT = """  局域网访问（已开启，需密钥）：
    服务绑定 0.0.0.0，同网段设备可访问，但必须携带密钥。
    入口：  http://192.168.0.100:35035
    密钥：  E:\\llm-cpp\\api-key.txt   （首次启动自动生成，可手工加多行做轮换）
    调用示例：
      curl -H "Authorization: Bearer <密钥>" ^
           http://192.168.0.100:35035/v1/chat/completions ^
           -H "Content-Type: application/json" ^
           -d "{\\"messages\\":[{\\"role\\":\\"user\\",\\"content\\":\\"你好\\"}]}"
      Python(openai 库)：
        from openai import OpenAI
        c = OpenAI(base_url="http://192.168.0.100:35035/v1", api_key="<密钥>")
    防火墙：首次开放需以管理员身份运行 开放局域网端口.bat（选 1 放行 TCP 35035）。
           只想本机可用时，把 启动大模型.bat 里的 HOST 改回 127.0.0.1 并重启。

"""
anchor2 = "  重新编译（你本机，Visual Studio 生成器）："
assert anchor2 in t
t = t.replace(anchor2, LAN_TXT + anchor2, 1)
io.open(D, 'w', encoding='utf-8', newline='\r\n').write(t)
print('部署说明已更新')
