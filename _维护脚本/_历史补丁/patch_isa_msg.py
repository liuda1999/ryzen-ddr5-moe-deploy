# -*- coding: utf-8 -*-
"""修复 CPU 变体检查的自相矛盾输出：icelake 缺失时不应再打印"正常"。

注意：这里全部用 raw 字符串，避免反斜杠转义层级搞错。
"""
import io
import os

HERE = os.path.dirname(os.path.abspath(__file__))

# --- 环境检查脚本里的版本 ---
OLD_CHECK = r'''if exist "%BIN_DIR%\ggml-cpu-cascadelake.dll" (
  echo         [警告] ggml-cpu-cascadelake.dll 处于启用状态
  echo                它会抢在 icelake 之前被选中，导致 VBMI 指令失效
  echo                处理：启动大模型.bat 会自动改名为 .disabled
  set "WARN=1"
) else (
  echo         正常    icelake 变体优先，AVX-512 + VNNI + VBMI 生效
)
'''

NEW_CHECK = r'''if not exist "%BIN_DIR%\ggml-cpu-icelake.dll" goto :PISA_NONE
if exist "%BIN_DIR%\ggml-cpu-cascadelake.dll" (
  echo         [警告] ggml-cpu-cascadelake.dll 处于启用状态
  echo                它会抢在 icelake 之前被选中，导致 VBMI 指令失效
  echo                处理：启动大模型.bat 会自动改名为 .disabled
  set "WARN=1"
) else (
  echo         正常    icelake 变体优先，AVX-512 + VNNI + VBMI 生效
)
goto :PISA_END
:PISA_NONE
echo         提示    icelake 变体缺失，需重新编译补齐（见上方 [失败] 项）
:PISA_END
'''

# --- 启动脚本里的版本 ---
OLD_TOGGLE = r'''if exist "%BIN_DIR%\ggml-cpu-cascadelake.dll" (
  echo         [修正] 发现 ggml-cpu-cascadelake.dll，它会抢在 icelake 前面被选中，
  echo                导致 VBMI 指令失效。正在改名为 .disabled ...
  ren "%BIN_DIR%\ggml-cpu-cascadelake.dll" "ggml-cpu-cascadelake.dll.disabled" >nul 2>nul
  if exist "%BIN_DIR%\ggml-cpu-cascadelake.dll" (
    echo         [失败] 无法改名，请手动处理
    set "CHK_FAIL=1"
  ) else (
    echo         [修正完成] 现在会命中 icelake（AVX-512 + VNNI + VBMI）
  )
) else (
  echo         正常    icelake 变体优先，AVX-512 + VNNI + VBMI 生效
)
'''

NEW_TOGGLE = r'''if not exist "%BIN_DIR%\ggml-cpu-icelake.dll" goto :TISA_NONE
if exist "%BIN_DIR%\ggml-cpu-cascadelake.dll" (
  echo         [修正] 发现 ggml-cpu-cascadelake.dll，它会抢在 icelake 前面被选中，
  echo                导致 VBMI 指令失效。正在改名为 .disabled ...
  ren "%BIN_DIR%\ggml-cpu-cascadelake.dll" "ggml-cpu-cascadelake.dll.disabled" >nul 2>nul
  if exist "%BIN_DIR%\ggml-cpu-cascadelake.dll" (
    echo         [失败] 无法改名，请手动处理
    set "CHK_FAIL=1"
  ) else (
    echo         [修正完成] 现在会命中 icelake（AVX-512 + VNNI + VBMI）
  )
) else (
  echo         正常    icelake 变体优先，AVX-512 + VNNI + VBMI 生效
)
goto :TISA_END
:TISA_NONE
echo         提示    icelake 变体缺失，需重新编译补齐（见上方 [失败] 项）
:TISA_END
'''

for fname, old, new, marker in [
        ("gen_check.py", OLD_CHECK, NEW_CHECK, 'PISA_NONE'),
        ("gen_toggle.py", OLD_TOGGLE, NEW_TOGGLE, 'TISA_NONE')]:
    p = os.path.join(HERE, fname)
    s = io.open(p, encoding='utf-8').read()
    if marker in s:
        print('  已修复过', fname)
        continue
    assert old in s, ('未匹配 ' + fname)
    s = s.replace(old, new, 1)
    io.open(p, 'w', encoding='utf-8', newline='\r\n').write(s)
    print('  已修复', fname)
print('完成')
