# -*- coding: utf-8 -*-
"""修正 curl 示例里 JSON 的反斜杠层数（\\" 应为 \"）。"""
import io
import os

HERE = os.path.dirname(os.path.abspath(__file__))
P = os.path.join(HERE, "gen_toggle.py")
s = io.open(P, encoding='utf-8').read()

NEW = 'echo          -d "{\\"messages\\":[{\\"role\\":\\"user\\",\\"content\\":\\"hi\\"}]}"'

lines = s.split('\n')
hit = 0
for i, l in enumerate(lines):
    if l.strip().startswith('echo          -d "{'):
        lines[i] = NEW
        hit += 1

assert hit == 1, ('匹配到 %d 行，预期 1 行' % hit)
s = '\n'.join(lines)
io.open(P, 'w', encoding='utf-8', newline='\r\n').write(s)
print('已修正 curl 示例行')
