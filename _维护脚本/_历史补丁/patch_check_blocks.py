# -*- coding: utf-8 -*-
"""修复环境检查脚本里"同一括号块内先 set 再 echo"导致的变量展开为空问题。

bat 的括号块在解析时就把 %VAR% 展开，块内 set 的值在同块内 echo 出来是空的。
改法：拆成 goto 结构 + 子程序，让每条 echo 都不在块内。
"""
import io

P = r"E:\llm-cpp\_维护脚本\gen_check.py"
s = io.open(P, encoding='utf-8').read()

if 'P6_FREE' in s:
    print('已修复过，跳过')
    raise SystemExit(0)

# ---------- 1) 重写 [6/10] 端口状态 ----------
old6_start = s.find('echo [6/10] 端口 %PORT% 状态')
old6_end = s.find('echo [7/10] 内存与档位可行性')
assert old6_start > 0 and old6_end > old6_start, '6 段定位失败'

new6 = '''echo [6/10] 端口 %PORT% 状态
call :PORT_STATE
if "%PSTATE%"=="free" goto :P6_FREE
call :GET_OWNER
echo         占用中  PID %PPID% （%PNAME%）
goto :P6_END
:P6_FREE
echo         正常    端口空闲，可以启动
:P6_END
echo.

'''
s = s[:old6_start] + new6 + s[old6_end:]

# ---------- 2) 重写 [9/10] 当前服务状态 ----------
old9_start = s.find('echo [9/10] 当前服务状态')
old9_end = s.find('echo.\necho ============================================================\nif "%FAIL%"=="1" (')
assert old9_start > 0 and old9_end > old9_start, '9 段定位失败'

new9 = '''echo [9/10] 当前服务状态
call :DETECT_SRV
if not defined SRV_PID goto :P9_DOWN
call :GET_MEM
echo         运行中  PID %SRV_PID%，占用 %SRV_MEM% GB
call :READ_PIDFILE
if defined CUR_TIER echo                 档位 %CUR_TIER% 号，上下文 %CUR_CTX%，线程 %CUR_T%，启动于 %CUR_TIME%
echo                 访问 http://127.0.0.1:%PORT%
goto :P9_END
:P9_DOWN
echo         未运行
if exist "%PID_FILE%" (
  echo         [警告] 存在残留状态文件 %PID_FILE%，下次启动会自动清理
  set "WARN=1"
)
:P9_END

'''
s = s[:old9_start] + new9 + s[old9_end:]

# ---------- 3) 在 [7/10] 内存段补一句"已有服务在跑"的说明 ----------
anchor7 = 'call :TIER_LINE 5 极限档    65536 28 55\n'
assert anchor7 in s, '7 段锚点失败'
s = s.replace(
    anchor7,
    anchor7 +
    'call :DETECT_SRV\n'
    'if defined SRV_PID echo         ^(提示：当前已有服务在运行并占用内存，故上面的可用性判断会偏保守^)\n',
    1)

# ---------- 4) 追加子程序 ----------
PS = 'powers' + 'hell'
subs = '''
REM ============================================================
REM  子程序：取占用端口的进程名
REM ============================================================
:GET_OWNER
set "PNAME=未知进程"
for /f "usebackq delims=" %%a in (`__PS__ -NoProfile -Command "(Get-Process -Id %PPID% -ErrorAction SilentlyContinue).ProcessName"`) do set "PNAME=%%a"
exit /b 0

REM ============================================================
REM  子程序：检测 llama-server 进程
REM ============================================================
:DETECT_SRV
set "SRV_PID="
for /f "usebackq delims=" %%a in (`__PS__ -NoProfile -Command "$p=@(Get-Process -Name llama-server -ErrorAction SilentlyContinue); if($p.Count -gt 0){$p[0].Id}"`) do set "SRV_PID=%%a"
exit /b 0

REM ============================================================
REM  子程序：取进程占用内存（GB）
REM ============================================================
:GET_MEM
set "SRV_MEM=?"
for /f "usebackq delims=" %%a in (`__PS__ -NoProfile -Command "[math]::Round((Get-Process -Id %SRV_PID%).WorkingSet64/1GB,1)"`) do set "SRV_MEM=%%a"
exit /b 0

REM ============================================================
REM  子程序：读取上次启动记录（PID|档位|上下文|线程|时间）
REM ============================================================
:READ_PIDFILE
set "CUR_TIER="
set "CUR_CTX="
set "CUR_T="
set "CUR_TIME="
if not exist "%PID_FILE%" exit /b 0
for /f "usebackq tokens=1-5 delims=|" %%a in ("%PID_FILE%") do (
  set "CUR_TIER=%%b"
  set "CUR_CTX=%%c"
  set "CUR_T=%%d"
  set "CUR_TIME=%%e"
)
exit /b 0
'''.replace('__PS__', PS)

# 插到 BAT 字符串闭合之前
old_tail = "exit /b 0\n'''\n"
assert s.count(old_tail) == 1, s.count(old_tail)
s = s.replace(old_tail, "exit /b 0\n" + subs + "'''\n", 1)

io.open(P, 'w', encoding='utf-8', newline='\r\n').write(s)
print('gen_check.py 重构完成')
