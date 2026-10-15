# -*- coding: utf-8 -*-
"""全新分发目录里日志目录尚未创建是正常现象（启动时自动建），不应判为失败。"""
import io

P = r"E:\llm-cpp\_维护脚本\gen_check.py"
s = io.open(P, encoding='utf-8').read()

old = '''if exist "%LOG_DIR%" (
  echo         正常    日志目录 %LOG_DIR%
) else (
  echo         [失败]  日志目录不存在：%LOG_DIR%
  set "FAIL=1"
)
'''
new = '''if exist "%LOG_DIR%" (
  echo         正常    日志目录 %LOG_DIR%
) else (
  echo         提示    日志目录尚未创建，首次启动服务时会自动建立
)
'''
assert old in s, '日志目录段未匹配'
s = s.replace(old, new, 1)
io.open(P, 'w', encoding='utf-8', newline='\r\n').write(s)
print('已修正：日志目录缺失降级为提示')
