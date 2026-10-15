# -*- coding: utf-8 -*-
"""生成中文命名的环境与安全检查脚本（GBK + CRLF）。"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "环境检查.bat")

BAT = r'''@echo off
chcp 936 >nul 2>nul
setlocal EnableExtensions
title Qwen3.6-35B 本地大模型 环境与安全检查

REM ============================================================
REM   环境检查.bat —— 启动前的全量体检
REM   双击即可运行；任何一项 [失败] 都意味着启动会出问题。
REM ============================================================

set "ROOT=%~dp0"
set "BIN_DIR=%ROOT%llama.cpp\build-zen5\bin"
set "MODEL=%ROOT%llama.cpp\models\Qwen3.6-35B-A3B-UD-Q4_K_XL.gguf"
set "MMPROJ=%ROOT%llama.cpp\models\mmproj-BF16.gguf"
set "LOG_DIR=%ROOT%logs"
set "PID_FILE=%LOG_DIR%\server.pid"
set "KEY_FILE=%ROOT%api-key.txt"
set "PORT=35035"
set "FAIL=0"
set "WARN=0"

cls
echo ============================================================
echo   Qwen3.6-35B 本地大模型 · 环境与安全检查
echo ============================================================
echo.

echo [1/10] 可执行程序
call :CHK_FILE "%BIN_DIR%\llama-server.exe"
call :CHK_FILE "%BIN_DIR%\llama-cli.exe"
call :CHK_FILE "%BIN_DIR%\llama-bench.exe"
echo.

echo [2/10] 依赖动态库
call :CHK_FILE "%BIN_DIR%\llama.dll"
call :CHK_FILE "%BIN_DIR%\llama-common.dll"
call :CHK_FILE "%BIN_DIR%\ggml.dll"
call :CHK_FILE "%BIN_DIR%\ggml-base.dll"
echo         运行库（随包附带，目标机无需安装 VC++ Redist）
call :CHK_FILE "%BIN_DIR%\vcruntime140.dll"
call :CHK_FILE "%BIN_DIR%\msvcp140.dll"
call :CHK_FILE "%BIN_DIR%\vcomp140.dll"
echo.

echo [3/10] CPU 指令集后端（决定能否用满 AVX-512）
call :CHK_FILE "%BIN_DIR%\ggml-cpu-icelake.dll"
if not exist "%BIN_DIR%\ggml-cpu-icelake.dll" goto :PISA_NONE
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
echo.

echo [4/10] 模型文件
call :CHK_FILE "%MODEL%"
if exist "%MODEL%" (
  for /f "usebackq delims=" %%a in (`powershell -NoProfile -Command "[math]::Round((Get-Item -LiteralPath '%MODEL%').Length/1GB,2)"`) do set "MODEL_GB=%%a"
)
if exist "%MODEL%" echo         大小 %MODEL_GB% GB（完整约 21.3 GB，明显偏小说明文件损坏）
echo.

echo [5/10] 视觉投影（多模态，缺失不影响纯文本）
if exist "%MMPROJ%" (
  echo         正常    mmproj-BF16.gguf
) else (
  echo         [警告] 未找到 mmproj，将只能处理纯文本
  set "WARN=1"
)
echo.

echo [6/10] 端口 %PORT% 状态
call :PORT_STATE
if "%PSTATE%"=="free" goto :P6_FREE
call :GET_OWNER
echo         占用中  PID %PPID% （%PNAME%）
goto :P6_END
:P6_FREE
echo         正常    端口空闲，可以启动
:P6_END
echo.

echo [7/10] 内存与档位可行性
for /f "usebackq delims=" %%a in (`powershell -NoProfile -Command "[int]((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory/1024)"`) do set "FREE_MB=%%a"
for /f "usebackq delims=" %%a in (`powershell -NoProfile -Command "[int]((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory/1GB)"`) do set "TOTAL_GB=%%a"
set /a FREE_GB=%FREE_MB% / 1024
echo         物理总内存 %TOTAL_GB% GB，当前可用 %FREE_GB% GB
echo.
call :TIER_LINE 1 极速档    12288 24 28
call :TIER_LINE 2 实用档    16384 24 30
call :TIER_LINE 3 长文档档  24576 24 34
call :TIER_LINE 4 超长档    32768 24 38
call :TIER_LINE 5 极限档    65536 28 55
call :DETECT_SRV
if defined SRV_PID echo         ^(提示：当前已有服务在运行并占用内存，故上面的可用性判断会偏保守^)
echo.

echo [8/10] 磁盘与日志目录
set "DL=%ROOT:~0,1%"
for /f "usebackq delims=" %%a in (`powershell -NoProfile -Command "[int]((Get-PSDrive -Name '%DL%').Free/1GB)"`) do set "DISK_GB=%%a"
if %DISK_GB% LSS 2 (
  echo         [失败]  %DL%: 盘仅剩 %DISK_GB% GB，无法写日志
  set "FAIL=1"
) else (
  echo         正常    %DL%: 盘剩余 %DISK_GB% GB
)
if exist "%LOG_DIR%" (
  echo         正常    日志目录 %LOG_DIR%
) else (
  echo         提示    日志目录尚未创建，首次启动服务时会自动建立
)
if exist "%SystemRoot%\System32\curl.exe" (
  echo         正常    系统自带 curl（用于精确判断服务是否真正加载完成）
) else (
  echo         [警告]  缺少 curl，启动脚本会退化为只检测端口监听
  set "WARN=1"
)
echo.

echo [9/10] 当前服务状态
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

echo.

echo [10/10] 局域网访问
call :GET_LAN_IP
if defined LAN_IP goto :P10_HASIP
echo         [警告]  未检测到局域网 IPv4，其它设备可能无法访问
set "WARN=1"
goto :P10_KEY
:P10_HASIP
echo         本机 IP  %LAN_IP%
echo         入口     http://%LAN_IP%:%PORT%   ^(需携带密钥^)
:P10_KEY
if not exist "%KEY_FILE%" goto :P10_NOKEY
call :LOAD_KEY
if not defined API_KEY goto :P10_EMPTYKEY
echo         正常    访问密钥已就绪 %KEY_FILE%
goto :P10_FW
:P10_EMPTYKEY
echo         [警告]  密钥文件里没有有效密钥，局域网请求会被拒绝
set "WARN=1"
goto :P10_FW
:P10_NOKEY
echo         [警告]  密钥文件尚未生成（首次启动服务时会自动创建）
set "WARN=1"
:P10_FW
netsh advfirewall firewall show rule name="llama.cpp-%PORT%" >nul 2>&1
if not errorlevel 1 goto :P10_FWOK
echo         [警告]  未发现防火墙放行规则，局域网设备可能连不上
echo                 需用管理员身份执行一次：
echo                 netsh advfirewall firewall add rule name="llama.cpp-%PORT%" dir=in action=allow protocol=TCP localport=%PORT%
goto :P10_END
:P10_FWOK
echo         正常    防火墙已放行 TCP %PORT%
:P10_END
echo.
echo ============================================================
if "%FAIL%"=="1" (
  echo   结论：检查未通过（有 [失败] 项），请先修复后再启动。
  echo         缺少程序时请运行：重新编译.bat
) else (
  if "%WARN%"=="1" (
    echo   结论：可以启动，但有 [警告] 项，建议留意上面提示。
  ) else (
    echo   结论：全部通过，可以启动。
  )
  echo         启动命令：启动大模型.bat
)
echo ============================================================
echo.
pause
endlocal
exit /b 0

REM ============================================================
:CHK_FILE
if exist "%~1" (
  echo         正常    %~nx1
) else (
  echo         [失败]  缺少 %~1
  set "FAIL=1"
)
exit /b 0

:PORT_STATE
set "PSTATE=free"
set "PPID="
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%PORT% " ^| findstr /I "LISTENING"') do (
  set "PPID=%%a"
  set "PSTATE=busy"
)
if not defined PPID set "PSTATE=free"
exit /b 0

:TIER_LINE
set /a NEED=%~5 * 1024
set /a WARNLVL=%NEED% * 12 / 10
if %FREE_MB% LSS %NEED% (
  echo         不可用  档位 %~1 %~2  %~3 ctx / %~4 线程  需 %~5 GB  内存不足
) else (
  if %FREE_MB% LSS %WARNLVL% (
    echo         紧张    档位 %~1 %~2  %~3 ctx / %~4 线程  需 %~5 GB
  ) else (
    echo         可用    档位 %~1 %~2  %~3 ctx / %~4 线程  需 %~5 GB
  )
)
exit /b 0

REM ============================================================
REM  子程序：读取访问密钥（仅显示用）
REM ============================================================
:LOAD_KEY
set "API_KEY="
if not exist "%KEY_FILE%" exit /b 0
for /f "usebackq delims=" %%a in (`findstr /v "^#" "%KEY_FILE%"`) do (
  if not defined API_KEY set "API_KEY=%%a"
)
exit /b 0

REM ============================================================
REM  子程序：获取局域网 IPv4（排除回环与 169.254）
REM ============================================================
:GET_LAN_IP
set "LAN_IP="
set "IPTMP=%TEMP%\llm_lan_ip_check.txt"
powershell -NoProfile -Command "$a=Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue; foreach($i in $a){ if($i.IPAddress -notlike '127.*' -and $i.IPAddress -notlike '169.254.*'){ Write-Output $i.IPAddress; break } }" > "%IPTMP%" 2>nul
if exist "%IPTMP%" (
  for /f "usebackq delims=" %%a in ("%IPTMP%") do if not defined LAN_IP set "LAN_IP=%%a"
  del "%IPTMP%" >nul 2>nul
)
exit /b 0

REM ============================================================
REM  子程序：取占用端口的进程名
REM ============================================================
:GET_OWNER
set "PNAME=未知进程"
for /f "usebackq delims=" %%a in (`powershell -NoProfile -Command "(Get-Process -Id %PPID% -ErrorAction SilentlyContinue).ProcessName"`) do set "PNAME=%%a"
exit /b 0

REM ============================================================
REM  子程序：检测 llama-server 进程
REM ============================================================
:DETECT_SRV
set "SRV_PID="
for /f "usebackq delims=" %%a in (`powershell -NoProfile -Command "$p=@(Get-Process -Name llama-server -ErrorAction SilentlyContinue); if($p.Count -gt 0){$p[0].Id}"`) do set "SRV_PID=%%a"
exit /b 0

REM ============================================================
REM  子程序：取进程占用内存（GB）
REM ============================================================
:GET_MEM
set "SRV_MEM=?"
for /f "usebackq delims=" %%a in (`powershell -NoProfile -Command "[math]::Round((Get-Process -Id %SRV_PID%).WorkingSet64/1GB,1)"`) do set "SRV_MEM=%%a"
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
'''

with open(OUT, 'wb') as f:
    f.write(BAT.replace('\n', '\r\n').encode('gbk', errors='strict'))
print("written:", OUT, os.path.getsize(OUT), "bytes")
