# -*- coding: utf-8 -*-
"""修复 patch_check.py 把子程序追加到 BAT 字符串之外的问题。"""
import io

P = r"E:\llm-cpp\_维护脚本\gen_check.py"
s = io.open(P, encoding='utf-8').read()
lines = s.split('\n')

# 找到写入代码行的位置，其后的内容是被错误追加的子程序
idx = None
for i, l in enumerate(lines):
    if l.startswith('print("written:", OUT'):
        idx = i
        break
assert idx is not None, 'print 行未找到'

sub = '\n'.join(lines[idx + 1:]).strip('\n')
assert ':GET_LAN_IP' in sub, '追加内容里没有子程序'
head = '\n'.join(lines[:idx + 1]) + '\n'

# 把子程序插到 BAT 字符串闭合之前
old = "exit /b 0\n'''\n"
assert head.count(old) == 1, head.count(old)
head = head.replace(old, "exit /b 0\n\n" + sub + "\n'''\n", 1)

io.open(P, 'w', encoding='utf-8', newline='\r\n').write(head)
print('修复完成，文件行数:', head.count('\n'))
