# -*- coding: utf-8 -*-
"""补上 HERE/ROOT 定义（上一步只换了 OUT 行）。"""
import io
import os

HERE_DIR = os.path.dirname(os.path.abspath(__file__))

DEFS = ('HERE = os.path.dirname(os.path.abspath(__file__))\n'
        'ROOT = os.path.dirname(HERE)\n')

for name in ["gen_toggle.py", "gen_check.py", "gen_firewall.py"]:
    p = os.path.join(HERE_DIR, name)
    s = io.open(p, encoding='utf-8').read()
    if 'HERE = os.path.dirname' in s:
        print('  已有定义', name)
        continue
    anchor = 'OUT = os.path.join(ROOT, '
    i = s.find(anchor)
    assert i > 0, (name, '未找到 OUT 行')
    s = s[:i] + DEFS + s[i:]
    io.open(p, 'w', encoding='utf-8', newline='\r\n').write(s)
    print('  已补 HERE/ROOT', name)
print('完成')
