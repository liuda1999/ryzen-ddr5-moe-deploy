# -*- coding: utf-8 -*-
"""临时插桩：在交互路径的关键行之间插入 ASCII 标记，用于定位"命令语法不正确"。"""
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
P = os.path.join(HERE, "gen_toggle.py")
s = io.open(P, encoding='utf-8').read()

MARK = 'REM __DBG_MARK__'

PAIRS = [
    ('set /p "TIER=  请输入档位编号 [2] : "\n', 'echo DBG-A\n'),
    ('if "%TIER%"=="" set "TIER=2"\n', 'echo DBG-B\n'),
    ('if "%TIER%"=="0" exit /b 0\n', 'echo DBG-C\n'),
    ('if defined THINK_FIXED goto :DO_START\n', 'echo DBG-D\n'),
    (':STEP_THINK\ncall :APPLY_TIER\n', 'echo DBG-E\n'),
    ('if not defined CTX goto :DO_START\n', 'echo DBG-F\n'),
]

if MARK in s:
    print('already instrumented')
    raise SystemExit(0)

for anchor, dbg in PAIRS:
    if anchor not in s:
        print('!! anchor missing:', anchor[:40].encode('unicode_escape').decode())
        continue
    s = s.replace(anchor, anchor + dbg, 1)

s = s.replace('BAT = r', MARK + '\nBAT = r', 1) if False else s
# 记录已插桩
io.open(P, 'w', encoding='utf-8', newline='\r\n').write(s + '\n# ' + MARK + '\n')
print('instrumented')
