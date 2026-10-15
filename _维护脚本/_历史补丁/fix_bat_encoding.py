"""
把工作区里的 .bat 文件从 UTF-8 转为 GBK(cp936) 编码。
中文 Windows 的 cmd 默认按 GBK 解析批处理文件，UTF-8 中文会被误判字节，
导致括号/管道等结构字符被破坏（表现为 '语法不正确'、命令无法识别）。
同时把 GBK 无法表示的符号（★ → ✔ → ─ 等）替换成安全字符。
"""
import pathlib
import sys

ROOT = pathlib.Path("E:/llm-cpp")
BATS = [
    "llm.bat",
    "check-env.bat",
    "run-llama-cli.bat",
    "run-llama-server.bat",
    "build-from-source.bat",
]

# GBK 无法表示 / 容易引发解析问题的符号 -> 安全替代
REPL = {
    "★": "*",
    "☆": "*",
    "✔": "[OK]",
    "✘": "[X]",
    "✅": "[OK]",
    "❌": "[X]",
    "→": "->",
    "←": "<-",
    "─": "-",
    "│": "|",
    "═": "=",
    "┌": "+",
    "└": "+",
    "├": "+",
    "┬": "+",
    "┴": "+",
    "┼": "+",
    "┐": "+",
    "┘": "+",
    "┤": "+",
    "≥": ">=",
    "≤": "<=",
    "×": "x",
    "≈": "~",
    "【": "[",
    "】": "]",
}

changed = []
for name in BATS:
    p = ROOT / name
    if not p.exists():
        print(f"  skip   {name} (不存在)")
        continue
    raw = p.read_bytes()
    try:
        text = raw.decode("utf-8")
        src = "utf-8"
    except UnicodeDecodeError:
        text = raw.decode("gbk", errors="replace")
        src = "gbk"

    for k, v in REPL.items():
        text = text.replace(k, v)

    # cmd 要求 CRLF 换行；LF-only 会导致 call :label、括号块解析错乱
    text = text.replace("\r\n", "\n").replace("\n", "\r\n")

    out = text.encode("gbk", errors="replace")
    p.write_bytes(out)
    changed.append(name)
    print(f"  fixed  {name}  (源 {src}, {len(raw)} -> {len(out)} bytes)")

print()
print(f"共处理 {len(changed)} 个文件：{', '.join(changed)}")
