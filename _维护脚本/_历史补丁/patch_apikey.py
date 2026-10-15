# -*- coding: utf-8 -*-
"""把 --api-key-file <路径> 改成 --api-key <值>。

原因：实测 llama-server 的 --api-key-file 无法打开含中文的路径
      （报 error: failed to open file 'E:\\...\\api-key.txt'），
      而 --model 用同样的中文路径却正常 —— 属于该参数自身的限制。
      密钥本身是纯 ASCII，直接作为参数传值即可彻底绕开路径编码问题。
"""
import io
import os

HERE = os.path.dirname(os.path.abspath(__file__))
P = os.path.join(HERE, "gen_toggle.py")
s = io.open(P, encoding='utf-8').read()

# ---- 1) 启动命令改用 --api-key ----
old_cmd = '--host %HOST% --port %PORT% --api-key-file "%KEY_FILE%" --ctx-size'
new_cmd = '--host %HOST% --port %PORT% --api-key %API_KEY% --ctx-size'
assert old_cmd in s, '启动命令未匹配'
s = s.replace(old_cmd, new_cmd, 1)

# ---- 2) LOAD_KEY 支持多 key 轮换（累积拼接，避免块内变量展开问题）----
old_load = '''for /f "usebackq delims=" %%a in (`findstr /v "^#" "%KEY_FILE%"`) do (
  if not defined API_KEY set "API_KEY=%%a"
)
exit /b 0
'''
new_load = '''for /f "usebackq delims=" %%a in (`findstr /v "^#" "%KEY_FILE%"`) do call :APPEND_KEY "%%a"
exit /b 0

:APPEND_KEY
if not defined API_KEY goto :AK_FIRST
set "API_KEY=%API_KEY%,%~1"
exit /b 0

:AK_FIRST
set "API_KEY=%~1"
exit /b 0
'''
assert old_load in s, 'LOAD_KEY 未匹配'
s = s.replace(old_load, new_load, 1)

# ---- 3) 启动前确保密钥可用 ----
old_start = '''cls
echo ============================================================
echo   启动前安全与环境检查
echo ============================================================'''
new_start = '''cls
echo ============================================================
echo   启动前安全与环境检查
echo ============================================================
'''
s = s.replace(old_start, new_start, 1)

anchor = '''start "Qwen3.6-35B 服务窗口（最小化）" /MIN cmd /c'''
guard = '''call :LOAD_KEY
if not defined API_KEY (
  echo [错误] 没有可用的访问密钥，已阻止启动。
  echo        请检查 %KEY_FILE% 是否存在且至少有一行非注释内容。
  exit /b 1
)

'''
assert anchor in s, 'start 命令锚点未匹配'
s = s.replace(anchor, guard + anchor, 1)

io.open(P, 'w', encoding='utf-8', newline='\r\n').write(s)
print('gen_toggle.py 已改为 --api-key 传值方式')
