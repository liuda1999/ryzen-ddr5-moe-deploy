# -*- coding: utf-8 -*-
"""让两个脚本的依赖检查项也校验随包附带的 VC++ 运行时 DLL。"""
import io

RUNTIME_CHECK = '''echo         运行库（随包附带，目标机无需安装 VC++ Redist）
call :CHK_FILE "%BIN_DIR%\\vcruntime140.dll"
call :CHK_FILE "%BIN_DIR%\\msvcp140.dll"
call :CHK_FILE "%BIN_DIR%\\vcomp140.dll"
'''

TARGETS = [
    (r"E:\llm-cpp\_维护脚本\gen_toggle.py",
     'call :CHK_FILE "%BIN_DIR%\\ggml-base.dll"\n'),
    (r"E:\llm-cpp\_维护脚本\gen_check.py",
     'call :CHK_FILE "%BIN_DIR%\\ggml-base.dll"\n'),
]

for path, anchor in TARGETS:
    s = io.open(path, encoding='utf-8').read()
    if 'vcruntime140.dll' in s:
        print(path, '已包含，跳过')
        continue
    assert anchor in s, (path, 'anchor missing')
    s = s.replace(anchor, anchor + RUNTIME_CHECK, 1)
    io.open(path, 'w', encoding='utf-8', newline='\r\n').write(s)
    print(path, '已更新')
