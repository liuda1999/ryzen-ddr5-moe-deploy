# -*- coding: utf-8 -*-
"""静态检查生成的 .bat，专抓那些「上机才炸」的写法。

用法：
    python _维护脚本\\check_bat.py

检查项：
  1. 括号块内 echo 展开的变量，其取值是否含半角括号
     —— %VAR% 在 if ( ) 块内展开时，值里出现 ) 会提前闭合块，
        实测报错「此时不应有 experts」。这类 bug 只有运行时才暴露，
        所以这里做静态扫描：找出「块内被 echo 的变量」∩「取值含半角括号的变量」。
  2. 行尾残留空格导致的多余空格（可选提示）
  3. GBK 编码检查：任何无法用 GBK 编码的字符（生成的 bat 是 GBK+CRLF）
  4. 括号总体平衡（忽略 REM 行，注释里的括号不算数）
"""
import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BATS = ["启动大模型.bat", "环境检查.bat", "开放局域网端口.bat"]
GEN = ["gen_toggle.py", "gen_check.py", "gen_firewall.py"]

han_paren = re.compile(r"[()]")


def load_bat(name):
    path = os.path.join(ROOT, name)
    if not os.path.exists(path):
        return None, None
    raw = open(path, "rb").read()
    return raw, raw.decode("gbk", errors="replace")


def check_gbk(name, raw):
    try:
        raw.decode("gbk")
        return []
    except UnicodeDecodeError as e:
        return ["%s: 非 GBK 字符 %r（偏移 %d）" % (name, raw[e.start:e.start + 4], e.start)]


def check_balance(name, text):
    d = dmin = 0
    for i, ln in enumerate(text.split("\r\n"), 1):
        if ln.strip().startswith("REM"):
            continue
        d += ln.count("(") - ln.count(")")
        dmin = min(dmin, d)
    if d == 0 and dmin >= 0:
        return []
    return ["%s: 括号不平衡（终值 %d，最低 %d）" % (name, d, dmin)]


def collect_var_values():
    """从生成器里收集每个变量的所有赋值文本（只取 set "VAR=..." 那一行）。"""
    vals = {}
    for g in GEN:
        p = os.path.join(HERE, g)
        if not os.path.exists(p):
            continue
        for ln in io.open(p, encoding="utf-8").read().split("\n"):
            m = re.match(r'\s*set\s+"?([A-Za-z_][A-Za-z0-9_]*)=(.*)$', ln)
            if not m:
                continue
            var, val = m.group(1).upper(), m.group(2)
            vals.setdefault(var, []).append(val)
    return vals


def block_echoed_vars(text):
    """找出在 if ( ) / for ( ) 块内被 echo 的变量名（单行 if 不算）。"""
    in_block = 0
    used = {}
    for i, ln in enumerate(text.split("\r\n"), 1):
        s = ln.strip()
        opens = ln.count("(") - ln.count(")")
        if in_block > 0 and s.startswith("echo"):
            for v in re.findall(r"%([A-Za-z_][A-Za-z0-9_]*)%", ln):
                used.setdefault(v.upper(), i)
        in_block += opens
        if in_block < 0:
            in_block = 0
    return used


def main():
    problems = []
    vals = collect_var_values()
    for name in BATS:
        raw, text = load_bat(name)
        if raw is None:
            problems.append("%s: 文件不存在（先跑生成器）" % name)
            continue
        problems += check_gbk(name, raw)
        problems += check_balance(name, text)
        for var, line in sorted(block_echoed_vars(text).items()):
            if var in vals and any(han_paren.search(x) for x in vals[var]):
                problems.append(
                    "%s 第 %d 行：块内 echo 的 %%%s%% 取值含半角括号，会把 if 块提前闭合"
                    % (name, line, var))

    if problems:
        print("发现 %d 个问题：" % len(problems))
        for p in problems:
            print("  -", p)
        sys.exit(1)
    print("检查通过：GBK 编码正常、括号平衡、块内无括号变量展开风险。")


if __name__ == "__main__":
    main()
