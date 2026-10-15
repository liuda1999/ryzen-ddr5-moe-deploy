@echo off
chcp 936 >nul 2>nul
setlocal EnableExtensions
title Qwen3.6-35B 本地大模型 一键开关

REM ============================================================
REM   启动大模型.bat  ——  二合一开关（启动 / 关闭 / 重启 / 状态）
REM
REM   双击运行：
REM     服务未运行  ->  先做环境与安全检查，通过后按档位启动
REM     服务已运行  ->  默认关闭服务（也可选择重启、打开网页、看日志）
REM
REM   命令行用法：
REM     启动大模型.bat               交互模式（自动判断启动或关闭）
REM     启动大模型.bat start  [1-5]  启动（档位可省，默认 2）
REM     启动大模型.bat stop          关闭
REM     启动大模型.bat restart [1-5] 重启
REM     启动大模型.bat status        只看状态
REM     启动大模型.bat check         只做环境与安全检查
REM
REM   深度思考（推理链）：
REM     默认关闭 —— 关闭后首个字更快出现、生成 token 更省。
REM     交互模式下会在选完档位后询问；也可用命令行直接指定：
REM       启动大模型.bat start 2 think     开启深度思考（回答更严谨，但更慢）
REM       启动大模型.bat start 2 nothink   关闭深度思考（快）
REM
REM   局域网访问：
REM     服务默认绑定 0.0.0.0，局域网其它设备可访问 http://<本机IP>:35035，
REM     但必须携带密钥（首次启动自动生成到根目录 api-key.txt）。
REM     只想本机可用时，把下面的 HOST 改回 127.0.0.1。
REM
REM   可在任意位置追加 quiet 参数进入静默模式（计划任务 / 开机自启用）：
REM     启动大模型.bat start 2 quiet
REM
REM   档位与实测数据详见：参数阶梯手册.md
REM ============================================================

set "ROOT=%~dp0"
set "BIN_DIR=%ROOT%llama.cpp\build-zen5\bin"
set "MODEL=%ROOT%llama.cpp\models\Qwen3.6-35B-A3B-UD-Q4_K_XL.gguf"
set "MMPROJ=%ROOT%llama.cpp\models\mmproj-BF16.gguf"
set "SERVER_EXE=%BIN_DIR%\llama-server.exe"
set "LOG_DIR=%ROOT%logs"
set "PID_FILE=%LOG_DIR%\server.pid"
REM 绑定地址：0.0.0.0 = 允许局域网其它设备访问（需配 --api-key-file 鉴权）
REM           127.0.0.1 = 仅本机可用（最安全，局域网连不上）
set "HOST=0.0.0.0"
set "CHECK_HOST=127.0.0.1"
set "PORT=35035"
REM 局域网访问密钥文件（首次启动自动生成；可手工加多行 key 做轮换）
set "KEY_FILE=%ROOT%api-key.txt"
set "READY_TIMEOUT=300"

REM quiet = 静默模式（供计划任务 / 开机自启调用：不等待按键、不打开浏览器）
set "QUIET=0"
if /i "%~1"=="quiet" set "QUIET=1"
if /i "%~2"=="quiet" set "QUIET=1"
if /i "%~3"=="quiet" set "QUIET=1"
if /i "%~4"=="quiet" set "QUIET=1"
if /i "%~5"=="quiet" set "QUIET=1"

REM 深度思考（推理链）：on = 开启，off = 关闭。关闭后响应更快、更省 token。
REM 默认关闭；命令行出现 think / nothink 时以此为准，不再在菜单里询问。
set "THINK=off"
set "THINK_FIXED="
if /i "%~1"=="think"   set "THINK=on"
if /i "%~2"=="think"   set "THINK=on"
if /i "%~3"=="think"   set "THINK=on"
if /i "%~4"=="think"   set "THINK=on"
if /i "%~1"=="nothink" set "THINK=off"
if /i "%~2"=="nothink" set "THINK=off"
if /i "%~3"=="nothink" set "THINK=off"
if /i "%~4"=="nothink" set "THINK=off"
if /i "%~1"=="think"   set "THINK_FIXED=1"
if /i "%~2"=="think"   set "THINK_FIXED=1"
if /i "%~3"=="think"   set "THINK_FIXED=1"
if /i "%~4"=="think"   set "THINK_FIXED=1"
if /i "%~1"=="nothink" set "THINK_FIXED=1"
if /i "%~2"=="nothink" set "THINK_FIXED=1"
if /i "%~3"=="nothink" set "THINK_FIXED=1"
if /i "%~4"=="nothink" set "THINK_FIXED=1"

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%" >nul 2>nul

REM ---------------- 参数模式 ----------------
if /i "%~1"=="status"  goto :STATUS_ONLY
if /i "%~1"=="check"   goto :ENV_CHECK_ONLY
if /i "%~1"=="start"   goto :ARG_START
if /i "%~1"=="stop"    goto :ARG_STOP
if /i "%~1"=="restart" goto :ARG_RESTART
if "%~1"==""           goto :MAIN
echo [错误] 未知参数：%~1
echo.
echo 用法：启动大模型.bat [start^|stop^|restart^|status^|check] [档位1-5]
echo.
call :PAUSE_IF
exit /b 1

REM ============================================================
:MAIN
call :DETECT
if defined SRV_PID goto :MENU_RUNNING
goto :MENU_STOPPED

REM ============================================================
:ARG_START
if not "%~2"=="" set "TIER=%~2"
if not defined TIER set "TIER=2"
call :DETECT
if defined SRV_PID (
  echo [提示] 服务已在运行（PID %SRV_PID%），无需重复启动。
  echo        再次运行本脚本即可关闭，或用：启动大模型.bat restart
  exit /b 0
)
goto :DO_START

:ARG_STOP
call :DETECT
if not defined SRV_PID (
  echo [提示] 服务未在运行，无需关闭。
  if exist "%PID_FILE%" (
    echo [清理] 删除残留的状态文件。
    del "%PID_FILE%" >nul 2>nul
  )
  exit /b 0
)
goto :DO_STOP

:ARG_RESTART
if not "%~2"=="" set "TIER=%~2"
call :DETECT
if not defined SRV_PID goto :DO_START
goto :DO_RESTART

:STATUS_ONLY
call :DETECT
if not defined SRV_PID goto :STATUS_DOWN
call :LOAD_PIDFILE
call :GET_LAN_IP
call :LOAD_KEY
echo.
echo ============================================================
echo   状态：服务正在运行
echo ============================================================
echo   进程 PID   %SRV_PID%
for /f "usebackq delims=" %%a in (`powershell -NoProfile -Command "[math]::Round((Get-Process -Id %SRV_PID%).WorkingSet64/1GB,1)"`) do set "SRV_MEM=%%a"
echo   内存占用   %SRV_MEM% GB
echo   配置档位   %CUR_TIER_NAME% （上下文 %CUR_CTX% / 线程 %CUR_T%）
call :SHOW_CUR_THINK
echo   启动时间   %CUR_TIME%
call :SHOW_ADDR
echo ============================================================
echo.
exit /b 0

REM ============================================================
REM  子程序：显示访问地址（局域网 + 本机 + 密钥）
REM ============================================================
:SHOW_ADDR
if defined LAN_IP (
  echo   局域网地址 http://%LAN_IP%:%PORT%      ^(其它设备用这个^)
) else (
  echo   局域网地址 ^(未检测到局域网 IPv4^)
)
echo   本机地址   http://127.0.0.1:%PORT%
echo   API 地址   http://127.0.0.1:%PORT%/v1/chat/completions
if defined API_KEY (
  echo   访问密钥   %API_KEY%
  echo   调用方式   请求头加 Authorization: Bearer 上面这串密钥
) else (
  echo   访问密钥   ^(未找到 %KEY_FILE%，局域网将无法通过鉴权^)
)
exit /b 0

:STATUS_DOWN
echo.
echo   状态：服务未运行（端口 %PORT% 空闲）
echo   运行 启动大模型.bat 即可启动。
echo.
exit /b 0

:ENV_CHECK_ONLY
call :SAFETY_CHECK
echo.
if "%CHK_FAIL%"=="1" (
  echo   结论：检查未通过，请先修复上面标记为 [失败] 的项目。
  call :PAUSE_IF
  exit /b 1
) else (
  echo   结论：检查全部通过，可以启动。
  call :PAUSE_IF
  exit /b 0
)

REM ============================================================
REM  服务已运行：默认动作是关闭
REM ============================================================
:MENU_RUNNING
call :LOAD_PIDFILE
call :GET_LAN_IP
call :LOAD_KEY
for /f "usebackq delims=" %%a in (`powershell -NoProfile -Command "[math]::Round((Get-Process -Id %SRV_PID%).WorkingSet64/1GB,1)"`) do set "SRV_MEM=%%a"
cls
echo ============================================================
echo   Qwen3.6-35B 本地大模型 · 服务正在运行
echo ============================================================
echo.
echo   进程 PID   %SRV_PID%
echo   内存占用   %SRV_MEM% GB
echo   配置档位   %CUR_TIER_NAME% （上下文 %CUR_CTX% / 线程 %CUR_T%）
call :SHOW_CUR_THINK
echo   启动时间   %CUR_TIME%
call :SHOW_ADDR
echo.
echo ------------------------------------------------------------
echo   1   关闭服务                         [默认]
echo   2   重启服务（可换档位）
echo   3   打开网页控制台
echo   4   查看最近日志
echo   0   退出，保持服务运行
echo ------------------------------------------------------------
echo.
set "ACT="
set /p "ACT=  请输入编号并回车 [1] : "
if "%ACT%"=="" set "ACT=1"
if "%ACT%"=="1" goto :DO_STOP
if "%ACT%"=="2" goto :DO_RESTART
if "%ACT%"=="3" goto :OPEN_WEB
if "%ACT%"=="4" goto :SHOW_LOG
if "%ACT%"=="0" exit /b 0
goto :MENU_RUNNING

REM ============================================================
REM  服务未运行：默认动作是启动
REM ============================================================
:MENU_STOPPED
cls
echo ============================================================
echo   Qwen3.6-35B 本地大模型 · 服务未运行
echo ============================================================
echo   模型   Qwen3.6-35B-A3B-UD-Q4_K_XL（MoE，21.3 GB）
echo   后端   纯 CPU · AVX-512 + VNNI + VBMI（icelake 变体）
echo.
echo ------------------------------------------------------------
echo   请选择配置档位（越往上生成越快，越往下上下文越长）
echo ------------------------------------------------------------
echo   1   极速档    12K 上下文 / 24 线程    约 13.3 t/s   需内存 ~28 GB
echo   2   实用档    16K 上下文 / 24 线程    约 12.7 t/s   需内存 ~30 GB   [默认]
echo   3   长文档    24K 上下文 / 24 线程    约 11.8 t/s   需内存 ~34 GB
echo   4   超长档    32K 上下文 / 24 线程    约 10.0 t/s   需内存 ~38 GB
echo   5   极限档    64K 上下文 / 28 线程    约  4.3 t/s   需内存 ~55 GB（很慢）
echo.
echo   0   退出
echo ------------------------------------------------------------
echo   说明：24 线程在所有档位的生成速度都优于 28 线程（内存带宽瓶颈）。
echo         完整实测数据见 参数阶梯手册.md
echo.
set "TIER="
set /p "TIER=  请输入档位编号 [2] : "
if "%TIER%"=="" set "TIER=2"
if "%TIER%"=="0" exit /b 0
if defined THINK_FIXED goto :DO_START
goto :STEP_THINK

REM ============================================================
REM  第二步：询问是否开启深度思考
REM ============================================================
:STEP_THINK
call :APPLY_TIER
if not defined CTX goto :DO_START
cls
echo ============================================================
echo   是否开启深度思考（推理链）？
echo ============================================================
echo   已选档位：%TIER_NAME%      %CTX% 上下文 / %THREADS% 线程
echo.
echo ------------------------------------------------------------
echo   Y   开启 —— 先推理再作答，逻辑题、数学题、复杂分析更稳妥
echo              代价：先输出一段思考内容，首个字更慢、更费 token
echo.
echo   N   关闭 —— 直接作答，响应更快、token 更省     [默认]
echo              适合：日常问答、翻译、摘要、改写润色
echo ------------------------------------------------------------
echo   提示：两种模式可随时切换，只要重新启动一次服务即可。
echo.
set "TK="
set /p "TK=  开启深度思考吗？(y/N) : "
if /i "%TK%"=="y" goto :TK_ON
set "THINK=off"
goto :DO_START
:TK_ON
set "THINK=on"
goto :DO_START

REM ============================================================
:DO_START
call :APPLY_TIER
if not defined CTX (
  echo [错误] 无效档位：%TIER%
  call :PAUSE_IF
  goto :MENU_STOPPED
)
cls
echo ============================================================
echo   启动前安全与环境检查
echo ============================================================

echo.
call :SAFETY_CHECK
if "%CHK_FAIL%"=="1" (
  echo.
  echo   检查未通过，已阻止启动（避免启动到一半崩溃或把系统拖到卡死）。
  echo.
  call :PAUSE_IF
  exit /b 1
)
call :MEM_CHECK
if "%MEM_BLOCK%"=="1" goto :MEM_NOT_ENOUGH
if "%MEM_WARN%"=="1" (
  echo.
  echo   [警告] 可用内存偏紧，继续启动可能导致系统明显卡顿甚至被系统杀掉进程。
  set "YN="
  set /p "YN=  仍要继续启动吗？(y/N) : "
  if /i not "%YN%"=="y" (
    echo   已取消，返回档位菜单。
    ping -n 2 127.0.0.1 >nul
    goto :MENU_STOPPED
  )
)

echo.
echo ============================================================
echo   正在启动：%TIER_NAME%
echo   上下文 %CTX%   线程 %THREADS%   端口 %PORT%
call :SHOW_THINK
echo ============================================================
echo.

set "TT=%time: =0%"
set "STAMP=%date:~0,4%%date:~5,2%%date:~8,2%-%TT:~0,2%%TT:~3,2%"
set "LOG_FILE=%LOG_DIR%\server-%STAMP%.log"

REM 只保留最近 10 份日志，避免长期堆积
for /f "skip=10 delims=" %%a in ('dir /b /o-d "%LOG_DIR%\server-*.log" 2^>nul') do del "%LOG_DIR%\%%a" >nul 2>nul

call :LOAD_KEY
if not defined API_KEY (
  echo [错误] 没有可用的访问密钥，已阻止启动。
  echo        请检查 %KEY_FILE% 是否存在且至少有一行非注释内容。
  exit /b 1
)

REM ------------------------------------------------------------
REM  在后台"无窗口"启动服务（任务栏也不出现窗口）。
REM
REM  做法：用 WScript.Shell 的 Run 方法，窗口风格传 0（隐藏窗口），
REM        第 3 个参数传 $false（不等待），于是服务在一个完全独立的
REM        隐藏进程里跑起来 —— 关掉本脚本窗口不会影响服务。
REM        日志重定向交给 cmd 完成。
REM
REM  三个必须注意的细节（都踩过）：
REM    1. 整条命令只用单引号 + [char]34 拼引号，命令里不出现双引号，
REM       这样不会被 cmd 的引号规则搅乱；
REM    2. cmd /c 后面的命令以引号开头时，必须在最外面再包一对引号
REM       （就是下面 $q + $q 那里），否则 cmd 会把引号剥掉、命令报错；
REM    3. 保留 < nul：避免服务持有本窗口的输入句柄导致脚本卡住。
REM ------------------------------------------------------------
powershell -NoProfile -Command "$q=[char]34; $c='cmd /c ' + $q + $q + '%SERVER_EXE%' + $q + ' --model ' + $q + '%MODEL%' + $q + ' --mmproj ' + $q + '%MMPROJ%' + $q + ' --host %HOST% --port %PORT% --api-key %API_KEY% --reasoning %THINK% --ctx-size %CTX% --threads %THREADS% --threads-batch %THREADS% --n-gpu-layers 0 < nul > ' + $q + '%LOG_FILE%' + $q + ' 2>&1' + $q; (New-Object -ComObject WScript.Shell).Run($c, 0, $false)"

echo [信息] 正在加载 21.3 GB 模型到内存，请稍候（通常 30~90 秒）...
echo [信息] 日志：%LOG_FILE%
echo.

REM 等待进程出现，取得 PID
set "SRV_PID="
set /a GOT=0
:WAIT_PID
ping -n 2 127.0.0.1 >nul
for /f "usebackq delims=" %%a in (`powershell -NoProfile -Command "$p=@(Get-Process -Name llama-server -ErrorAction SilentlyContinue); if($p.Count -gt 0){$p[0].Id}"`) do set "SRV_PID=%%a"
if defined SRV_PID goto :GOT_PID
set /a GOT+=1
if %GOT% GEQ 20 (
  echo [错误] 进程启动失败或已退出，请查看日志：
  echo        %LOG_FILE%
  if exist "%LOG_FILE%" powershell -NoProfile -Command "Get-Content -LiteralPath '%LOG_FILE%' -Tail 25"
  call :PAUSE_IF
  exit /b 1
)
goto :WAIT_PID

:GOT_PID
echo [信息] 进程已启动，PID = %SRV_PID%
echo [信息] 等待服务就绪（最长 %READY_TIMEOUT% 秒）...
set /a SEC=0
set /a SEC=0
set /a TICK=0
:WAIT_READY
ping -n 6 127.0.0.1 >nul
set /a SEC+=5
call :HEALTH_OK
if "%READY%"=="1" goto :READY_OK
if %SEC% GEQ %READY_TIMEOUT% goto :READY_TIMEOUT
set /a TICK+=1
if %TICK% LSS 3 goto :WAIT_READY
set "TICK=0"
echo        ... 已等待 %SEC% 秒（模型加载中）
goto :WAIT_READY

REM ============================================================
REM  子程序：就绪判定
REM  端口开始监听并不代表模型已加载完（此时 /health 返回 503
REM  "Loading model"），必须等到 /health 返回 200 才能算真正可用。
REM ============================================================
:HEALTH_OK
set "READY=0"
set "HTTPCODE="
if not exist "%SystemRoot%\System32\curl.exe" goto :HEALTH_BY_PORT
REM 注意：for /f 反引号内的命令不能以引号开头，否则 cmd 会把整串当成一个文件名
for /f "usebackq delims=" %%a in (`%SystemRoot%\System32\curl.exe -s -o nul -w "%%{http_code}" -m 5 http://%CHECK_HOST%:%PORT%/health`) do set "HTTPCODE=%%a"
if "%HTTPCODE%"=="200" set "READY=1"
exit /b 0

:HEALTH_BY_PORT
call :PORT_BUSY
if "%PORT_STATE%"=="busy" set "READY=1"
exit /b 0

:READY_TIMEOUT
echo.
echo [错误] 等待超时，服务未能在 %READY_TIMEOUT% 秒内就绪。
echo       请查看日志排查：%LOG_FILE%
if exist "%LOG_FILE%" powershell -NoProfile -Command "Get-Content -LiteralPath '%LOG_FILE%' -Tail 25"
call :PAUSE_IF
exit /b 1

:READY_OK
call :GET_LAN_IP
call :LOAD_KEY
>"%PID_FILE%" echo %SRV_PID%^|%TIER%^|%CTX%^|%THREADS%^|%STAMP%^|%THINK%
echo.
echo ============================================================
echo   启动成功，服务已就绪
echo ============================================================
echo   档位      %TIER_NAME%（上下文 %CTX% / 线程 %THREADS%）
call :SHOW_THINK
echo   进程 PID  %SRV_PID%
echo   日志      %LOG_FILE%
echo.
call :SHOW_API_BLOCK
echo.
if "%QUIET%"=="1" exit /b 0

set "YN="
set /p "YN=  是否打开网页控制台？(Y/n) : "
if /i "%YN%"=="n" goto :START_DONE
start "" http://%HOST%:%PORT%
:START_DONE
echo.
echo   提示：再次运行本脚本即可关闭服务（会释放内存）。
echo.
call :PAUSE_IF
exit /b 0

REM ============================================================
REM  子程序：显示思考模式（当前启动参数）
REM ============================================================
:SHOW_THINK
if /i "%THINK%"=="on" echo   深度思考 开启  ^(先推理再作答：更严谨，但更慢、更费 token^)
if /i not "%THINK%"=="on" echo   深度思考 关闭  ^(直接作答：更快、token 更省^)
exit /b 0

REM ============================================================
REM  子程序：显示思考模式（读自启动记录，供 status / 运行中菜单用）
REM ============================================================
:SHOW_CUR_THINK
if /i "%CUR_THINK%"=="on" echo   深度思考   开启
if /i not "%CUR_THINK%"=="on" echo   深度思考   关闭
exit /b 0

REM ============================================================
REM  子程序：显示本次服务的 API 信息，并把密钥复制到剪贴板
REM ============================================================
:SHOW_API_BLOCK
echo ------------------------------------------------------------
echo   ★ 本次服务 API（在下次重启服务前一直有效）
echo ------------------------------------------------------------
if defined LAN_IP echo   局域网地址   http://%LAN_IP%:%PORT%/v1
if not defined LAN_IP echo   局域网地址   ^(未检测到局域网 IPv4^)
echo   本机地址     http://127.0.0.1:%PORT%/v1
echo   访问密钥     %API_KEY%
echo.
echo   OpenAI 兼容客户端这样填：
echo     接口地址 / Base URL  =  上面任一地址
echo     API Key              =  上面这串密钥
echo     模型名               =  留空即可（单模型服务）
echo.
echo   curl 示例：
echo     curl -H "Authorization: Bearer %API_KEY%" \
echo          http://127.0.0.1:%PORT%/v1/chat/completions \
echo          -H "Content-Type: application/json" \
echo          -d "{\"messages\":[{\"role\":\"user\",\"content\":\"hi\"}]}"
echo.
echo   注意：密钥区分大小写、不要加 sk- 前缀；
echo         服务只认请求头 Authorization，不支持 ?api_key= 查询参数。
echo ------------------------------------------------------------
call :COPY_KEY
exit /b 0

:COPY_KEY
if not defined API_KEY exit /b 0
<nul set /p "=%API_KEY%"| clip >nul 2>nul
if errorlevel 1 exit /b 0
echo   密钥已复制到剪贴板，可直接粘贴到客户端。
exit /b 0

REM ============================================================
REM  内存不足：给出三条出路 + 各档位可行性，然后回档位菜单重选
REM ============================================================
:MEM_NOT_ENOUGH
echo.
echo ============================================================
echo   内存不足，已阻止启动
echo ============================================================
echo   本档位 %TIER_NAME%（%CTX% 上下文）需要约 %NEED_GB% GB，
echo   当前可用 %FREE_GB% GB。
echo.
call :SHOW_TIER_FIT
echo.
echo   三个解决办法，任选其一：
echo     1  关闭其它占内存的程序（浏览器、虚拟机、其它模型服务）后重试
echo     2  在下面标注为「可用」的档位里挑一个更小的
echo     3  换更小的模型：把 GGUF 换成更小量化的版本，
echo        再改本脚本顶部的 MODEL 变量后重新启动
echo.
if "%QUIET%"=="1" exit /b 1
echo   按回车返回档位菜单重新选择。
echo.
call :PAUSE_IF
goto :MENU_STOPPED

REM ============================================================
:DO_RESTART
REM 未指定档位时，沿用上次启动记录中的档位（读不到则回落到默认 2）
if not defined TIER (
  call :LOAD_PIDFILE
  if defined CUR_TIER set "TIER=%CUR_TIER%"
)
if not defined TIER set "TIER=2"
echo.
echo [信息] 正在重启服务...
call :DO_STOP
ping -n 4 127.0.0.1 >nul
goto :DO_START

REM ============================================================
:DO_STOP
echo.
echo ============================================================
echo   正在关闭服务（PID %SRV_PID%）
echo ============================================================
for /f "usebackq delims=" %%a in (`powershell -NoProfile -Command "[math]::Round((Get-Process -Id %SRV_PID% -ErrorAction SilentlyContinue).WorkingSet64/1GB,1)"`) do set "SRV_MEM=%%a"
echo [信息] 当前占用内存：%SRV_MEM% GB，正在释放...
taskkill /PID %SRV_PID% >nul 2>nul
set /a WAIT=0
:STOP_WAIT
ping -n 3 127.0.0.1 >nul
set /a WAIT+=2
call :DETECT
if not defined SRV_PID goto :STOP_OK
if %WAIT% GEQ 6 goto :STOP_FORCE
goto :STOP_WAIT
:STOP_FORCE
echo [警告] 优雅退出超时，改为强制结束进程...
taskkill /F /PID %SRV_PID% >nul 2>nul
ping -n 4 127.0.0.1 >nul
call :DETECT
if defined SRV_PID (
  echo [错误] 进程 %SRV_PID% 无法结束，请手动在任务管理器中关闭。
  call :PAUSE_IF
  exit /b 1
)
:STOP_OK
if exist "%PID_FILE%" del "%PID_FILE%" >nul 2>nul
set /a SEC=0
:STOP_PORT_WAIT
ping -n 3 127.0.0.1 >nul
set /a SEC+=2
call :PORT_BUSY
if "%PORT_STATE%"=="free" goto :STOP_PORT_OK
if %SEC% GEQ 20 (
  echo [警告] 进程已结束，但端口 %PORT% 仍未释放（系统回收需要一点时间）。
  goto :STOP_DONE
)
goto :STOP_PORT_WAIT
:STOP_PORT_OK
echo [完成] 端口 %PORT% 已释放。
:STOP_DONE
echo.
echo   服务已关闭，内存已释放。
echo.
call :PAUSE_IF
exit /b 0

REM ============================================================
:OPEN_WEB
echo.
echo [信息] 正在打开 http://%HOST%:%PORT% ...
start "" http://%HOST%:%PORT%
echo [完成] 服务保持运行。
echo.
call :PAUSE_IF
exit /b 0

:SHOW_LOG
echo.
set "LASTLOG="
for /f "delims=" %%a in ('dir /b /o-d "%LOG_DIR%\server-*.log" 2^>nul') do (
  set "LASTLOG=%%a"
  goto :SHOWLOG_GOT
)
:SHOWLOG_GOT
echo ---------------- 最近 30 行日志 ----------------
if not defined LASTLOG (
  echo   暂无日志文件
) else (
  echo   文件：%LASTLOG%
  echo.
  powershell -NoProfile -Command "Get-Content -LiteralPath '%LOG_DIR%\%LASTLOG%' -Tail 30"
)
echo ------------------------------------------------
echo.
call :PAUSE_IF
exit /b 0

REM ============================================================
REM  子程序：档位 -> 参数
REM ============================================================
:APPLY_TIER
set "CTX="
if "%TIER%"=="1" ( set "CTX=12288" & set "THREADS=24" & set "TIER_NAME=极速档" & set "NEED_GB=28" )
if "%TIER%"=="2" ( set "CTX=16384" & set "THREADS=24" & set "TIER_NAME=实用档" & set "NEED_GB=30" )
if "%TIER%"=="3" ( set "CTX=24576" & set "THREADS=24" & set "TIER_NAME=长文档档" & set "NEED_GB=34" )
if "%TIER%"=="4" ( set "CTX=32768" & set "THREADS=24" & set "TIER_NAME=超长档" & set "NEED_GB=38" )
if "%TIER%"=="5" ( set "CTX=65536" & set "THREADS=28" & set "TIER_NAME=极限档" & set "NEED_GB=55" )
exit /b 0

REM ============================================================
REM  子程序：按当前可用内存列出各档位可行性
REM ============================================================
:SHOW_TIER_FIT
echo   当前可用内存 %FREE_GB% GB（共 %TOTAL_GB% GB）下的档位情况：
call :FIT_LINE 1 极速档   28
call :FIT_LINE 2 实用档   30
call :FIT_LINE 3 长文档档 34
call :FIT_LINE 4 超长档   38
call :FIT_LINE 5 极限档   55
exit /b 0

:FIT_LINE
set /a FIT_NEED=%~3 * 1024
if %FREE_MB% LSS %FIT_NEED% echo        不可用   档位 %~1  %~2   需 %~3 GB
if %FREE_MB% GEQ %FIT_NEED% echo        可用     档位 %~1  %~2   需 %~3 GB
exit /b 0

REM ============================================================
REM  子程序：检测服务进程
REM ============================================================
:DETECT
set "SRV_PID="
for /f "usebackq delims=" %%a in (`powershell -NoProfile -Command "$p=@(Get-Process -Name llama-server -ErrorAction SilentlyContinue); if($p.Count -gt 0){$p[0].Id}"`) do set "SRV_PID=%%a"
exit /b 0

REM ============================================================
REM  子程序：端口状态（free / busy）
REM ============================================================
:PORT_BUSY
set "PORT_STATE=free"
set "PORT_PID="
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%PORT% " ^| findstr /I "LISTENING"') do (
  set "PORT_PID=%%a"
  set "PORT_STATE=busy"
)
if not defined PORT_PID set "PORT_STATE=free"
exit /b 0

REM ============================================================
REM  子程序：读取上次启动记录
REM ============================================================
:LOAD_PIDFILE
set "CUR_PID="
set "CUR_TIER="
set "CUR_CTX="
set "CUR_T="
set "CUR_TIME="
set "CUR_THINK=off"
set "CUR_TIER_NAME=未知档位"
if not exist "%PID_FILE%" exit /b 0
for /f "usebackq tokens=1-6 delims=|" %%a in ("%PID_FILE%") do (
  set "CUR_PID=%%a"
  set "CUR_TIER=%%b"
  set "CUR_CTX=%%c"
  set "CUR_T=%%d"
  set "CUR_TIME=%%e"
  set "CUR_THINK=%%f"
)
if not defined CUR_THINK set "CUR_THINK=off"
if "%CUR_TIER%"=="1" set "CUR_TIER_NAME=极速档"
if "%CUR_TIER%"=="2" set "CUR_TIER_NAME=实用档"
if "%CUR_TIER%"=="3" set "CUR_TIER_NAME=长文档档"
if "%CUR_TIER%"=="4" set "CUR_TIER_NAME=超长档"
if "%CUR_TIER%"=="5" set "CUR_TIER_NAME=极限档"
exit /b 0

REM ============================================================
REM  子程序：确保访问密钥存在（首次运行自动生成，不覆盖已有文件）
REM ============================================================
:ENSURE_KEY
if exist "%KEY_FILE%" exit /b 0
set "NEWKEY="
for /f "usebackq delims=" %%a in (`powershell -NoProfile -Command "[guid]::NewGuid().ToString('N')"`) do set "NEWKEY=%%a"
if not defined NEWKEY exit /b 0
(
echo # llama.cpp 服务访问密钥（局域网设备调用时必须携带）
echo # 每行一个密钥，可写多行做轮换；以井号开头的行是注释。
echo # 修改后需重启服务才生效。文件位置：%KEY_FILE%
echo %NEWKEY%
) > "%KEY_FILE%"
exit /b 0

REM ============================================================
REM  子程序：读取访问密钥（仅用于显示；鉴权由 llama-server 自己完成）
REM ============================================================
:LOAD_KEY
set "API_KEY="
if not exist "%KEY_FILE%" exit /b 0
for /f "usebackq delims=" %%a in (`findstr /v "^#" "%KEY_FILE%"`) do call :APPEND_KEY "%%a"
exit /b 0

:APPEND_KEY
if not defined API_KEY goto :AK_FIRST
set "API_KEY=%API_KEY%,%~1"
exit /b 0

:AK_FIRST
set "API_KEY=%~1"
exit /b 0

REM ============================================================
REM  子程序：获取局域网 IPv4（排除回环与 169.254 自动私有地址）
REM  说明：PowerShell 里要用管道，先落临时文件再读，
REM        避免 for /f 反引号内管道转义的老问题。
REM ============================================================
:GET_LAN_IP
set "LAN_IP="
set "IPTMP=%TEMP%\llm_lan_ip.txt"
powershell -NoProfile -Command "$a=Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue; foreach($i in $a){ if($i.IPAddress -notlike '127.*' -and $i.IPAddress -notlike '169.254.*'){ Write-Output $i.IPAddress; break } }" > "%IPTMP%" 2>nul
if exist "%IPTMP%" (
  for /f "usebackq delims=" %%a in ("%IPTMP%") do if not defined LAN_IP set "LAN_IP=%%a"
  del "%IPTMP%" >nul 2>nul
)
exit /b 0

REM ============================================================
REM  子程序：环境与安全检查
REM ============================================================
:SAFETY_CHECK
set "CHK_FAIL=0"
set "CHK_N=0"

call :CHK_NEXT
echo [1/9] 可执行程序
call :CHK_FILE "%SERVER_EXE%"
call :CHK_FILE "%BIN_DIR%\llama-cli.exe"

call :CHK_NEXT
echo [2/9] 依赖动态库
call :CHK_FILE "%BIN_DIR%\llama.dll"
call :CHK_FILE "%BIN_DIR%\llama-common.dll"
call :CHK_FILE "%BIN_DIR%\ggml.dll"
call :CHK_FILE "%BIN_DIR%\ggml-base.dll"
echo         运行库（随包附带，目标机无需安装 VC++ Redist）
call :CHK_FILE "%BIN_DIR%\vcruntime140.dll"
call :CHK_FILE "%BIN_DIR%\msvcp140.dll"
call :CHK_FILE "%BIN_DIR%\vcomp140.dll"

call :CHK_NEXT
echo [3/9] CPU 指令集后端（AVX-512 关键）
call :CHK_FILE "%BIN_DIR%\ggml-cpu-icelake.dll"
if not exist "%BIN_DIR%\ggml-cpu-icelake.dll" goto :TISA_NONE
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

call :CHK_NEXT
echo [4/9] 模型文件
call :CHK_FILE "%MODEL%"
if exist "%MODEL%" (
  for /f "usebackq delims=" %%a in (`powershell -NoProfile -Command "[math]::Round((Get-Item -LiteralPath '%MODEL%').Length/1GB,2)"`) do set "MODEL_GB=%%a"
)
if exist "%MODEL%" echo         大小 %MODEL_GB% GB（完整模型应约 21.3 GB）

call :CHK_NEXT
echo [5/9] 视觉投影（多模态）
if exist "%MMPROJ%" (
  echo         正常    mmproj-BF16.gguf
) else (
  echo         [警告]  未找到 mmproj，将以纯文本模式启动（不处理图片）
)

call :CHK_NEXT
echo [6/9] 端口 %PORT% 占用
call :PORT_BUSY
if "%PORT_STATE%"=="busy" (
  echo         [失败]  端口已被进程 %PORT_PID% 占用，本次启动会失败
  for /f "usebackq delims=" %%a in (`powershell -NoProfile -Command "(Get-Process -Id %PORT_PID% -ErrorAction SilentlyContinue).ProcessName"`) do echo                 占用者：%%a
  set "CHK_FAIL=1"
) else (
  echo         正常    端口空闲
)

call :CHK_NEXT
echo [7/9] 磁盘剩余空间
set "DL=%ROOT:~0,1%"
for /f "usebackq delims=" %%a in (`powershell -NoProfile -Command "[int]((Get-PSDrive -Name '%DL%').Free/1GB)"`) do set "DISK_GB=%%a"
if %DISK_GB% LSS 2 (
  echo         [失败]  %DL%: 盘仅剩 %DISK_GB% GB，无法写日志
  set "CHK_FAIL=1"
) else (
  echo         正常    %DL%: 盘剩余 %DISK_GB% GB
)

call :CHK_NEXT
echo [8/9] 重复实例
call :DETECT
if defined SRV_PID (
  echo         [失败]  已有 llama-server 实例在运行（PID %SRV_PID%），不能重复启动
  set "CHK_FAIL=1"
) else (
  echo         正常    无残留实例
)
call :CLEAN_STALE_PID

call :CHK_NEXT
echo [9/9] 访问密钥与局域网
call :ENSURE_KEY
if exist "%KEY_FILE%" (
  call :LOAD_KEY
  if defined API_KEY (
    echo         正常    访问密钥已就绪（%KEY_FILE%）
  ) else (
    echo         [失败]  密钥文件里没有有效密钥
    set "CHK_FAIL=1"
  )
) else (
  echo         [失败]  无法创建密钥文件 %KEY_FILE%
  set "CHK_FAIL=1"
)
call :GET_LAN_IP
if defined LAN_IP (
  echo         提示    局域网入口 http://%LAN_IP%:%PORT%  ^(需带密钥^)
) else (
  echo         [警告]  未检测到局域网 IPv4，其它设备可能无法访问
)
exit /b 0

:CHK_NEXT
exit /b 0

:CHK_FILE
if exist "%~1" (
  echo         正常    %~nx1
) else (
  echo         [失败]  缺少 %~1
  set "CHK_FAIL=1"
)
exit /b 0

:CLEAN_STALE_PID
if exist "%PID_FILE%" (
  call :DETECT
  if not defined SRV_PID (
    echo         [清理] 删除残留的状态文件（服务并不在运行）
    del "%PID_FILE%" >nul 2>nul
  )
)
exit /b 0

REM ============================================================
REM  子程序：内存安全检查
REM ============================================================
:MEM_CHECK
set "MEM_BLOCK=0"
set "MEM_WARN=0"
for /f "usebackq delims=" %%a in (`powershell -NoProfile -Command "[int]((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory/1024)"`) do set "FREE_MB=%%a"
for /f "usebackq delims=" %%a in (`powershell -NoProfile -Command "[int]((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory/1GB)"`) do set "TOTAL_GB=%%a"
set /a FREE_GB=%FREE_MB% / 1024
set /a NEED_MB=%NEED_GB% * 1024
set /a WARN_MB=%NEED_MB% * 12 / 10
echo.
echo   内存检查：总内存 %TOTAL_GB% GB，当前可用 %FREE_GB% GB，本档位需要约 %NEED_GB% GB
if %FREE_MB% LSS %NEED_MB% (
  echo   [失败]  可用内存不足，启动会触发系统大量换页甚至卡死
  set "MEM_BLOCK=1"
) else (
  if %FREE_MB% LSS %WARN_MB% (
    echo   [警告]  可用内存接近需求下限，建议先关闭占用内存的程序
    set "MEM_WARN=1"
  ) else (
    echo   正常    内存充足
  )
)
exit /b 0

REM ============================================================
REM  子程序：等待按键（静默模式下直接跳过）
REM ============================================================
:PAUSE_IF
if "%QUIET%"=="1" exit /b 0
pause
exit /b 0
