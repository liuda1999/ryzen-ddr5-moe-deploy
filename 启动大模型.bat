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
REM     启动大模型.bat start  [1-4]  启动（档位可省，默认 2）
REM     启动大模型.bat stop          关闭
REM     启动大模型.bat restart [1-4] 重启
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
REM   GPU 混合卸载（只针对 NVIDIA 独立显卡；核显与非 N 卡一律按纯 CPU）：
REM     默认开启（GPU_MODE=auto）。把「每 token 必读」的那部分权重放进显存，
REM     体积最大的 MoE 专家权重仍留在内存（它们每 token 只用到 8/256）。
REM     实测：卸载到显存的非专家权重仅约 1.3 GiB（40 层），占总量约 6%；
REM     32K 上下文的 KV 只占约 640 MiB（该模型为混合注意力，KV 增长很慢）。
REM     GPU 不可用时（没 N 卡 / 没后端 / 没 CUDA 运行库 / 显存太小）会自动
REM     退回纯 CPU，不会阻止启动 —— 所以默认开着是安全的，CPU 永远兜底。
REM     关闭方式（三者其一）：
REM       a) 把下面的 GPU_MODE 改成 off
REM       b) 命令行加一个 nogpu 参数        —— 启动大模型.bat start 2 nogpu
REM       c) 想自己控层数：把 GPU_MODE 改成 manual，再填下面几个值
REM     想临时试一次：启动大模型.bat start 2 gpu
REM     缺后端 / 缺 CUDA 运行库请跑 环境检查.bat 的「GPU 支持自检」。
REM     原理与显存预算详见：参数阶梯手册.md 的「GPU 混合卸载」章节。
REM
REM   可在任意位置追加 quiet 参数进入静默模式（计划任务 / 开机自启用）：
REM     启动大模型.bat start 2 quiet
REM
REM   档位与实测数据详见：参数阶梯手册.md
REM ============================================================

set "ROOT=%~dp0"
set "BIN_DIR=%ROOT%llama.cpp\build-zen5\bin"
set "MODEL=%ROOT%llama.cpp\models\Qwen3.6-35B-A3B-uncensored-heretic-Q4_K_M.gguf"
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

REM ============================================================
REM  GPU 混合卸载（只针对 NVIDIA 独立显卡）
REM  默认 auto：有 N 卡就压榨显存提速，没有就自动退回纯 CPU。
REM
REM   auto   = 默认值。自动探测，按显存算出卸几层；不可用则退回纯 CPU
REM   off    = 完全不启用，传 --n-gpu-layers 0（与旧版逐字节一致）
REM   manual = 完全按下面几个值拼参数
REM ============================================================
set "GPU_MODE=auto"
REM manual 模式专用（auto 模式忽略它们）：
set "GPU_DEVICE="         REM 指定设备，如 CUDA0；留空=自动
set "GPU_LAYERS="         REM -ngl 值：数字 / auto / all
set "CPU_MOE="            REM all（全部专家留内存）或层数，如 41
set "MOE_CACHE_MIB="      REM 专家显存缓存 MiB，0/留空=不用
set "KV_OFFLOAD="         REM on / off；off = KV 留内存（省显存，适合小显存卡）
REM auto 模式的参数（MiB）—— 取值来自 2026-10-15 在 GTX 1060 3GB 上的实测：
set "GPU_MIN_FREE_MIB=1536"   REM 空闲显存低于此值就不启用（再低收益太小）
set "GPU_LAYER_MIB=64"        REM 每层「非专家权重」约 64 MiB（本模型实测 2.53 GiB / 41 层）
set "GPU_RESERVE_MIB=448"     REM 桌面占用 + KV/计算缓冲 + CUDA 上下文，属硬开销，不含安全垫
set "GPU_NLAYER=41"           REM 模型层数，用来给算出的层数封顶
REM 层数是按「显卡总显存」算的，不是按 llama.cpp 报的空闲显存：
REM   llama.cpp 的 free 会额外扣掉一份保留量（本卡报 2460，而实际可用约 2880），
REM   用 total 算才能压榨到位。实测 32~41 层速度基本持平（生成 18~21 t/s），
REM   所以这里取「压满但不超过模型层数」。
REM
REM 为什么故意不留余量（448 只是桌面+KV+上下文的硬开销，不是安全垫）：
REM   本机这张 GTX 1060 3GB 是「能找到的最老、显存最低」的卡，属于最坏情况；
REM   主流消费级 N 卡普遍 4GB 起，而 4GB 上 (4096-448)/64 = 57 层同样会被
REM   GPU_NLAYER=41 封顶 —— 即 4GB 以上的卡本来就吃不满非专家权重那一份，
REM   余量天然更大、更不容易越界。所以「压满」对绝大多数设备都是安全的。
REM   代价：3GB 卡上若同时开着重度图形程序把桌面占用推高，仍可能越界分页
REM   （分页后生成速度掉到约 1/2.4）。想要保险就把 GPU_RESERVE_MIB 调大。
REM 换模型时 GPU_LAYER_MIB 与 GPU_NLAYER 都要跟着改：
REM   GPU_NLAYER   = 模型层数
REM   GPU_LAYER_MIB = 模型里「非专家权重」总大小 ÷ 层数
REM 前者可从 GGUF 元数据看到；后者可用 _维护脚本\gguf_tensor_stats.py 量。
REM ============================================================

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

REM GPU 开关：默认就是 auto（有 N 卡就启用），这里只处理命令行的临时覆盖：
REM   nogpu -> 本次强制纯 CPU      gpu -> 本次强制启用
REM 命令行优先级最高，不改文件，重启后回到文件里的设置。
if /i "%~1"=="gpu"   goto :GPUCLI_ON
if /i "%~2"=="gpu"   goto :GPUCLI_ON
if /i "%~3"=="gpu"   goto :GPUCLI_ON
if /i "%~4"=="gpu"   goto :GPUCLI_ON
if /i "%~5"=="gpu"   goto :GPUCLI_ON
if /i "%~1"=="nogpu" set "GPU_MODE=off"
if /i "%~2"=="nogpu" set "GPU_MODE=off"
if /i "%~3"=="nogpu" set "GPU_MODE=off"
if /i "%~4"=="nogpu" set "GPU_MODE=off"
if /i "%~5"=="nogpu" set "GPU_MODE=off"
goto :GPUCLI_END
:GPUCLI_ON
set "GPU_MODE=auto"
:GPUCLI_END

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
echo 用法：启动大模型.bat [start^|stop^|restart^|status^|check] [档位1-4]
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
set "GPU_REQ=%CUR_GPU%"
set "GPU_ARGS=%CUR_GPU_ARGS%"
set "GPU_LOG_STAMP=%CUR_TIME%"
call :SHOW_GPU_ACTUAL
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
set "GPU_REQ=%CUR_GPU%"
set "GPU_ARGS=%CUR_GPU_ARGS%"
set "GPU_LOG_STAMP=%CUR_TIME%"
call :SHOW_GPU_ACTUAL
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
echo   模型   Qwen3.6-35B-A3B-uncensored-heretic Q4_K_M（MoE，21.2 GB）
echo   后端   纯 CPU（AVX-512+VNNI+VBMI）· 有 N 卡时自动启用显存混合卸载
echo.
echo ------------------------------------------------------------
echo   请选择配置档位（越往下上下文越长；有 N 卡时自动启用显存加速）
echo ------------------------------------------------------------
echo   1   极速档    12K 上下文 / 24 线程    约 22~24 t/s   需内存 ~24 GB
echo   2   实用档    16K 上下文 / 24 线程    约 22~24 t/s   需内存 ~24 GB   [默认]
echo   3   长文档    24K 上下文 / 24 线程    约 21~24 t/s   需内存 ~25 GB
echo   4   超长档    32K 上下文 / 24 线程    约 20~24 t/s   需内存 ~25 GB
echo.
echo   0   退出
echo ------------------------------------------------------------
echo   说明：区间上限=短对话，下限=上下文填满后；生成速度与上下文长度关系不大，
echo         填满 32K 时约 20 t/s。无 N 卡时按纯 CPU 运行（约 15 t/s）。
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

REM GPU 探测与参数组装：不可用时会自动退回纯 CPU，不阻断启动
call :GPU_PROBE
call :BUILD_GPU_ARGS

echo.
echo ============================================================
echo   正在启动：%TIER_NAME%
echo   上下文 %CTX%   线程 %THREADS%   端口 %PORT%
call :SHOW_THINK
call :SHOW_GPU_PLAN
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
powershell -NoProfile -Command "$q=[char]34; $c='cmd /c ' + $q + $q + '%SERVER_EXE%' + $q + ' --model ' + $q + '%MODEL%' + $q + ' --mmproj ' + $q + '%MMPROJ%' + $q + ' --host %HOST% --port %PORT% --api-key %API_KEY% --reasoning %THINK% --ctx-size %CTX% --threads %THREADS% --threads-batch %THREADS% %GPU_ARGS% < nul > ' + $q + '%LOG_FILE%' + $q + ' 2>&1' + $q; (New-Object -ComObject WScript.Shell).Run($c, 0, $false)"

echo [信息] 正在加载 19.8 GB 模型到内存，请稍候（通常 30~90 秒）...
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
>"%PID_FILE%" echo %SRV_PID%^|%TIER%^|%CTX%^|%THREADS%^|%STAMP%^|%THINK%^|%GPU_MODE%^|%GPU_ARGS%
echo.
echo ============================================================
echo   启动成功，服务已就绪
echo ============================================================
echo   档位      %TIER_NAME%（上下文 %CTX% / 线程 %THREADS%）
call :SHOW_THINK
set "GPU_REQ=%GPU_MODE%"
set "GPU_LOG_STAMP=%STAMP%"
call :SHOW_GPU_ACTUAL
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
if "%TIER%"=="1" ( set "CTX=12288" & set "THREADS=24" & set "TIER_NAME=极速档" & set "NEED_GB=24" )
if "%TIER%"=="2" ( set "CTX=16384" & set "THREADS=24" & set "TIER_NAME=实用档" & set "NEED_GB=24" )
if "%TIER%"=="3" ( set "CTX=24576" & set "THREADS=24" & set "TIER_NAME=长文档档" & set "NEED_GB=25" )
if "%TIER%"=="4" ( set "CTX=32768" & set "THREADS=24" & set "TIER_NAME=超长档" & set "NEED_GB=25" )
exit /b 0

REM ============================================================
REM  子程序：按当前可用内存列出各档位可行性
REM ============================================================
:SHOW_TIER_FIT
echo   当前可用内存 %FREE_GB% GB（共 %TOTAL_GB% GB）下的档位情况：
call :FIT_LINE 1 极速档   24
call :FIT_LINE 2 实用档   24
call :FIT_LINE 3 长文档档 25
call :FIT_LINE 4 超长档   25
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
set "CUR_GPU=off"
set "CUR_GPU_ARGS="
set "CUR_TIER_NAME=未知档位"
if not exist "%PID_FILE%" exit /b 0
for /f "usebackq tokens=1-8 delims=|" %%a in ("%PID_FILE%") do (
  set "CUR_PID=%%a"
  set "CUR_TIER=%%b"
  set "CUR_CTX=%%c"
  set "CUR_T=%%d"
  set "CUR_TIME=%%e"
  set "CUR_THINK=%%f"
  set "CUR_GPU=%%g"
  set "CUR_GPU_ARGS=%%h"
)
if not defined CUR_THINK set "CUR_THINK=off"
if not defined CUR_GPU set "CUR_GPU=off"
if "%CUR_TIER%"=="1" set "CUR_TIER_NAME=极速档"
if "%CUR_TIER%"=="2" set "CUR_TIER_NAME=实用档"
if "%CUR_TIER%"=="3" set "CUR_TIER_NAME=长文档档"
if "%CUR_TIER%"=="4" set "CUR_TIER_NAME=超长档"
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
REM  子程序：探测可用 GPU
REM
REM  判定依据是 llama-server --list-devices 的实际输出 —— 它来自后端本身，
REM  报的是「该后端真正能用的显存」，比 WMI / 注册表可靠得多
REM  （WMI 的 AdapterRAM 在 >4 GB 时会溢出，注册表值不反映当前占用）。
REM
REM  包里只编 CUDA 后端，所以「列表里有设备」等价于「有可用的 N 卡」；
REM  核显与非 N 卡根本不会出现在列表里，无需额外排除逻辑。
REM
REM  以下任一情况都会让列表解析不出内容 → GPU_AVAILABLE=0
REM  → 自动退回纯 CPU，不阻断启动：
REM    没有 ggml-cuda.dll / 没有 N 卡 / 驱动过老 /
REM    缺 CUDA 运行库(cublas) / 后端 API 版本不匹配
REM
REM  注意（踩过一次的坑）：重定向会先把输出文件建出来，所以
REM  「文件存在」并不能说明探测成功，必须靠「解析出来的内容是否为空」判断。
REM ============================================================
:GPU_PROBE
REM 同一轮里可能被调用两次（检查项一次、启动前一次），结果缓存起来避免重复探测
if "%GPU_PROBED%"=="1" exit /b 0
set "GPU_PROBED=1"
set "GPU_AVAILABLE=0"
set "GPU_NAME="
set "GPU_DEV_ID="
set "GPU_DEV_IDS="
set "GPU_TOTAL_MIB=0"
set "GPU_FREE_MIB=0"
set "GPU_PROBE_NOTE="
if not exist "%BIN_DIR%\ggml-cuda.dll" (
  set "GPU_PROBE_NOTE=未找到 CUDA 后端 ggml-cuda.dll（见 环境检查.bat 第 11 项）"
  exit /b 0
)
REM stdout 与 stderr 都收：设备列表走 stdout，后端的告警走 stderr
set "GPUTMP=%TEMP%\llm_gpu_probe.txt"
"%SERVER_EXE%" --list-devices > "%GPUTMP%" 2>&1
call :CP_RESET
REM 解析形如：  CUDA0: NVIDIA GeForce GTX 1660 (6144 MiB, 5312 MiB free)
REM 四组：设备名 / 型号描述 / 总显存 / 空闲显存。收集全部设备，
REM 主设备取第一台，全部设备名供 manual 模式的 --device 校验用。
for /f "usebackq delims=" %%a in (`powershell -NoProfile -Command "$t=Get-Content -LiteralPath '%GPUTMP%' -ErrorAction SilentlyContinue; foreach($l in $t){ if($l -match '^\s*([^:\s]+)\s*:\s*(.+?)\s*\((\d+)\s*MiB,\s*(\d+)\s*MiB free\)'){ Write-Output ($matches[1] + '|' + $matches[2] + '|' + $matches[3] + '|' + $matches[4]) } }"`) do call :GPU_TAKE "%%a"
del "%GPUTMP%" >nul 2>nul
if not defined GPU_DEV_ID (
  call :GPU_WHY
  exit /b 0
)
set "GPU_AVAILABLE=1"
exit /b 0

:GPU_TAKE
for /f "tokens=1,2,3,4 delims=|" %%a in ("%~1") do call :GPU_TAKE_ONE "%%a" "%%b" "%%c" "%%d"
exit /b 0

REM 这里必须用 call 逐条处理：for 循环体内的 %VAR% 在整块解析时只展开一次，
REM 直接写 set "GPU_DEV_IDS=%GPU_DEV_IDS% ..." 会丢掉前面的累积结果。
:GPU_TAKE_ONE
if not defined GPU_DEV_ID (
  set "GPU_DEV_ID=%~1"
  set "GPU_NAME=%~2"
  set "GPU_TOTAL_MIB=%~3"
  set "GPU_FREE_MIB=%~4"
)
set "GPU_DEV_IDS=%GPU_DEV_IDS% %~1"
exit /b 0

REM ============================================================
REM  子程序：探测不到设备时细分原因
REM  旧卡用户最常缺的是 CUDA 运行库 —— 它不随显卡驱动安装，
REM  只给一句「后端未列出设备」会让人无从下手。
REM
REM  运行库的查找顺序与 Windows 的 DLL 解析一致：先看 bin\（exe 同目录），
REM  再看 PATH。装过 CUDA / PyTorch 的机器往往只有 PATH 里有。
REM ============================================================
:GPU_WHY
call :GPU_LIB_OK cublas64_12.dll
set "GW_A=%GW_LIB_OK%"
call :GPU_LIB_OK cublasLt64_12.dll
set "GW_B=%GW_LIB_OK%"
if "%GW_A%%GW_B%"=="11" goto :GW_NEXT
set "GPU_PROBE_NOTE=缺 CUDA 运行库 cublas64_12.dll / cublasLt64_12.dll，后端无法加载"
exit /b 0
:GW_NEXT
if not exist "%SystemRoot%\System32\nvcuda.dll" (
  set "GPU_PROBE_NOTE=缺少 nvcuda.dll：NVIDIA 显卡驱动没装好或版本过老"
  exit /b 0
)
set "GPU_PROBE_NOTE=后端没认出设备：驱动过老、后端与运行库版本不匹配、或本机确实没有 N 卡"
exit /b 0

:GPU_LIB_OK
set "GW_LIB_OK=0"
if exist "%BIN_DIR%\%~1" set "GW_LIB_OK=1"
if "%GW_LIB_OK%"=="1" exit /b 0
where %~1 >nul 2>nul
if not errorlevel 1 set "GW_LIB_OK=1"
exit /b 0

REM ============================================================
REM  子程序：把控制台代码页改回 936
REM
REM  必须调：llama-server 启动时会在 common_init() 里执行
REM  SetConsoleOutputCP(CP_UTF8) / SetConsoleCP(CP_UTF8)，
REM  而探测是在「本脚本所在的这个控制台」里跑的，于是它把整个窗口
REM  的代码页改成了 65001 —— 之后本脚本用 GBK 写的中文全部变成乱码
REM  （连 pause 的提示都会变英文）。实测 936 -> 65001。
REM  所以每次在控制台里调用过 llama-server 之后都要改回来。
REM ============================================================
:CP_RESET
chcp 936 >nul 2>nul
exit /b 0

REM ============================================================
REM  子程序：按模式组装 GPU 参数
REM
REM  auto 模式的核心组合是「--n-gpu-layers N --cpu-moe」：
REM    --cpu-moe      把体积最大的 MoE 专家权重留在内存
REM                   （占模型 88.1%，每 token 只激活 8/256）
REM    --n-gpu-layers 于是上显存的只有「每 token 必读」的注意力/稠密/输出等，
REM                   本模型全量是 2.53 GiB；N 表示前 N 层上显存
REM  为什么不用 --fit 自动决定 N：见 auto 分支里的实测说明（它会放弃，
REM  然后把全部层塞进显存，速度反而掉到 1/2.4）。
REM ============================================================
:BUILD_GPU_ARGS
set "GPU_ARGS=--n-gpu-layers 0"
set "GPU_STRATEGY=纯 CPU"
if /i "%GPU_MODE%"=="off" (
  set "GPU_STRATEGY=纯 CPU（GPU_MODE=off，已手动关闭）"
  exit /b 0
)
if "%GPU_AVAILABLE%"=="1" goto :BGA_HAVE
set "GPU_STRATEGY=纯 CPU（已请求 GPU 但不可用，已自动退回）"
exit /b 0

:BGA_HAVE
if /i "%GPU_MODE%"=="manual" goto :BGA_MANUAL
REM ---------- auto ----------
REM 这里刻意不用 --fit，原因见下方注释；改为自己按显存余量算卸几层。
REM
REM 为什么不用 --fit（2026-10-15 在 GTX 1060 3GB 上实测踩到）：
REM   --cpu-moe 会设置「张量缓冲区覆盖」，而 --fit 一旦发现用户已设置覆盖
REM   就直接放弃（日志原文：failed to fit params ... tensor_buft_overrides
REM   already set by user, abort）。放弃之后 n_gpu_layers 落到「全部层」，
REM   于是 42/42 层全塞进显存 —— 需要 3036 MiB，可用仅 2208 MiB，
REM   WDDM 只能把显存分页到系统内存，生成速度从 14.6 掉到 6.1 t/s。
REM
REM 换成自己算，实测有效（16K 上下文、GTX 1060 3GB，生成速度 t/s）：
REM   0 层 14.5 / 32 层 19.5 / 36 层 18.8 / 38 层 19.8 / 40 层 20.8 / 41 层 21.4
REM   加 -nkvo（KV 留内存）只剩 14.9 —— 等于没收益，所以 KV 必须留在显存。
REM   32 层往上速度基本持平，所以直接压到模型层数上限最划算。
REM 层数按「显卡总显存」算，不是按 llama.cpp 报的空闲显存：
REM   它的 free 会额外扣掉一份保留量（本卡报 2460，实际可用约 2880），
REM   用 total 才算得满。代价是没留余量 —— 若同时开着重度图形程序把桌面
REM   占用推高，仍可能越界分页（分页后速度掉到约 1/2.4）；想留量就调大
REM   GPU_RESERVE_MIB。
if %GPU_FREE_MIB% LSS %GPU_MIN_FREE_MIB% goto :BGA_SMALL
if not defined GPU_TOTAL_MIB goto :BGA_SMALL
set /a BGA_SPACE=%GPU_TOTAL_MIB% - %GPU_RESERVE_MIB%
if %BGA_SPACE% LSS %GPU_LAYER_MIB% goto :BGA_SMALL
set /a BGA_N=%BGA_SPACE% / %GPU_LAYER_MIB%
if %BGA_N% LSS 1 goto :BGA_SMALL
if %BGA_N% GTR %GPU_NLAYER% set /a BGA_N=%GPU_NLAYER%
REM --parallel 1：只开一个并发槽。本地单人使用用不上多槽，而它让 KV cache
REM 不再按 4 份分配 —— 实测 prefill 27.3 -> 33.5 t/s、生成 20.3 -> 21.4 t/s，
REM 还少占一点显存。
set "GPU_ARGS=--n-gpu-layers %BGA_N% --cpu-moe --parallel 1"
set "GPU_STRATEGY=非专家权重上显存（%BGA_N% 层），专家留内存，单并发槽"
exit /b 0
:BGA_SMALL
set "GPU_STRATEGY=纯 CPU（空闲显存 %GPU_FREE_MIB% MiB，不足门槛 %GPU_MIN_FREE_MIB% MiB）"
exit /b 0

:BGA_MANUAL
REM ---------- manual ----------
set "GPU_ARGS="
if defined GPU_DEVICE call :CHECK_GPU_DEVICE
if defined GPU_DEVICE set "GPU_ARGS=--device %GPU_DEVICE%"
if defined GPU_LAYERS set "GPU_ARGS=%GPU_ARGS% --n-gpu-layers %GPU_LAYERS%"
if not defined GPU_LAYERS set "GPU_ARGS=%GPU_ARGS% --n-gpu-layers 0"
if /i "%CPU_MOE%"=="all" set "GPU_ARGS=%GPU_ARGS% --cpu-moe"
if defined CPU_MOE if /i not "%CPU_MOE%"=="all" set "GPU_ARGS=%GPU_ARGS% --n-cpu-moe %CPU_MOE%"
if defined MOE_CACHE_MIB set "GPU_ARGS=%GPU_ARGS% --moe-cache-mib %MOE_CACHE_MIB%"
if /i "%KV_OFFLOAD%"=="off" set "GPU_ARGS=%GPU_ARGS% -nkvo"
if /i "%KV_OFFLOAD%"=="on" set "GPU_ARGS=%GPU_ARGS% -kvo"
set "GPU_STRATEGY=手动指定"
exit /b 0

REM ============================================================
REM  子程序：核对手工指定的 --device
REM  llama-server 对写错的设备名是「直接报错退出」，服务根本起不来，
REM  所以在拼参数之前先跟后端列出的设备名核对一次，对不上就退回自动选择。
REM ============================================================
:CHECK_GPU_DEVICE
set "DEVOK="
for %%d in (%GPU_DEV_IDS%) do if /i "%%d"=="%GPU_DEVICE%" set "DEVOK=1"
if defined DEVOK exit /b 0
echo.
echo   [警告] GPU_DEVICE=%GPU_DEVICE% 不在后端列出的设备里
echo          后端探测到：%GPU_DEV_IDS%
echo          若照此启动，llama-server 会因 invalid device 直接退出，
echo          已改为自动选择设备。
set "GPU_DEVICE="
exit /b 0

REM ============================================================
REM  子程序：启动前显示 GPU 计划（GPU_MODE=off 时什么都不显示）
REM ============================================================
:SHOW_GPU_PLAN
if /i "%GPU_MODE%"=="off" exit /b 0
if "%GPU_AVAILABLE%"=="1" (
  echo   GPU 策略   %GPU_STRATEGY%
  echo   GPU 设备   %GPU_NAME%  ^(%GPU_TOTAL_MIB% MiB 总 / %GPU_FREE_MIB% MiB 空闲^)
) else (
  echo   GPU 策略   %GPU_STRATEGY%
  echo              %GPU_PROBE_NOTE%
)
exit /b 0

REM ============================================================
REM  子程序：从服务日志里读出「实际生效」的层分配
REM  需要外部先设置 GPU_LOG_STAMP（= 日志文件名里的时间戳）
REM  llama.cpp 会打印：
REM    load_tensors: offloaded 41/41 layers to GPU
REM ============================================================
:SHOW_GPU_ACTUAL
REM GPU_REQ / GPU_ARGS 由调用方设置：启动路径 = GPU_MODE / 本次参数，
REM status 与运行中菜单 = 记录下来的 CUR_GPU / CUR_GPU_ARGS。
REM 旧状态文件没有这些字段时为空，按 off 处理（不显示这行，与旧版输出一致）。
if "%GPU_LOG_STAMP%"=="" exit /b 0
set "GLOG=%LOG_DIR%\server-%GPU_LOG_STAMP%.log"
if not exist "%GLOG%" exit /b 0
set "GCLAUSE="
for /f "usebackq delims=" %%a in (`findstr /c:"load_tensors: offloaded" "%GLOG%"`) do set "GCLAUSE=%%a"
if defined GCLAUSE goto :SGA_SHOW
REM 取不到实际行是正常的：llama-server 在默认详细度下根本不打印层分配
REM （load_tensors: offloaded 只在 -lv 4 才输出，已实测），
REM 所以回落到启动时记录下来的实际参数。
if not defined GPU_REQ exit /b 0
if /i "%GPU_REQ%"=="off" exit /b 0
if not defined GPU_ARGS goto :SGA_NONE
if /i "%GPU_ARGS%"=="--n-gpu-layers 0" goto :SGA_NONE
echo   GPU 参数   %GPU_ARGS%
exit /b 0
:SGA_NONE
echo   GPU 未生效，本次为纯 CPU 运行（原因见 环境检查.bat 第 11 项）
exit /b 0
:SGA_SHOW
set "GCLAUSE=%GCLAUSE:*load_tensors: =%"
echo   GPU 层分配 %GCLAUSE%
exit /b 0

REM ============================================================
REM  子程序：环境与安全检查
REM ============================================================
:SAFETY_CHECK
set "CHK_FAIL=0"
set "CHK_N=0"

call :CHK_NEXT
echo [1/10] 可执行程序
call :CHK_FILE "%SERVER_EXE%"
call :CHK_FILE "%BIN_DIR%\llama-cli.exe"

call :CHK_NEXT
echo [2/10] 依赖动态库
call :CHK_FILE "%BIN_DIR%\llama.dll"
call :CHK_FILE "%BIN_DIR%\llama-common.dll"
call :CHK_FILE "%BIN_DIR%\ggml.dll"
call :CHK_FILE "%BIN_DIR%\ggml-base.dll"
echo         运行库（随包附带，目标机无需安装 VC++ Redist）
call :CHK_FILE "%BIN_DIR%\vcruntime140.dll"
call :CHK_FILE "%BIN_DIR%\msvcp140.dll"
call :CHK_FILE "%BIN_DIR%\vcomp140.dll"

call :CHK_NEXT
echo [3/10] CPU 指令集后端（AVX-512 关键）
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
echo [4/10] 模型文件
call :CHK_FILE "%MODEL%"
if exist "%MODEL%" (
  for /f "usebackq delims=" %%a in (`powershell -NoProfile -Command "[math]::Round((Get-Item -LiteralPath '%MODEL%').Length/1GB,2)"`) do set "MODEL_GB=%%a"
)
if exist "%MODEL%" echo         大小 %MODEL_GB% GB（完整模型应约 19.8 GB）

call :CHK_NEXT
echo [5/10] 视觉投影（多模态）
if exist "%MMPROJ%" (
  echo         正常    mmproj-BF16.gguf
) else (
  echo         [警告]  未找到 mmproj，将以纯文本模式启动（不处理图片）
)

call :CHK_NEXT
echo [6/10] 端口 %PORT% 占用
call :PORT_BUSY
if "%PORT_STATE%"=="busy" (
  echo         [失败]  端口已被进程 %PORT_PID% 占用，本次启动会失败
  for /f "usebackq delims=" %%a in (`powershell -NoProfile -Command "(Get-Process -Id %PORT_PID% -ErrorAction SilentlyContinue).ProcessName"`) do echo                 占用者：%%a
  set "CHK_FAIL=1"
) else (
  echo         正常    端口空闲
)

call :CHK_NEXT
echo [7/10] 磁盘剩余空间
set "DL=%ROOT:~0,1%"
for /f "usebackq delims=" %%a in (`powershell -NoProfile -Command "[int]((Get-PSDrive -Name '%DL%').Free/1GB)"`) do set "DISK_GB=%%a"
if %DISK_GB% LSS 2 (
  echo         [失败]  %DL%: 盘仅剩 %DISK_GB% GB，无法写日志
  set "CHK_FAIL=1"
) else (
  echo         正常    %DL%: 盘剩余 %DISK_GB% GB
)

call :CHK_NEXT
echo [8/10] 重复实例
call :DETECT
if defined SRV_PID (
  echo         [失败]  已有 llama-server 实例在运行（PID %SRV_PID%），不能重复启动
  set "CHK_FAIL=1"
) else (
  echo         正常    无残留实例
)
call :CLEAN_STALE_PID

call :CHK_NEXT
echo [9/10] 访问密钥与局域网
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

call :CHK_NEXT
echo [10/10] 显卡（NVIDIA 独显混合卸载）
REM 这一项只报「能不能用」，永远不设 [失败] —— GPU 不可用时服务照样能
REM 以纯 CPU 跑起来，不该因为显卡的事把启动拦掉。
REM 默认 GPU_MODE=auto，正常都走 :TGPU_REQ 去探测；能落到下面两条的，
REM 只可能是手动关了（命令行 nogpu，或把顶部 GPU_MODE 改成 off）。
if /i not "%GPU_MODE%"=="off" goto :TGPU_REQ
if not exist "%BIN_DIR%\ggml-cuda.dll" goto :TGPU_PLAIN
echo         提示    已关闭 GPU（GPU_MODE=off），本次按纯 CPU 运行
echo                 想启用：启动大模型.bat start 2 gpu   或把顶部 GPU_MODE 改成 auto
goto :TGPU_END
:TGPU_PLAIN
echo         提示    已关闭 GPU（GPU_MODE=off），本次按纯 CPU 运行
echo                 有 N 卡想加速：跑 环境检查.bat 看第 11 项「GPU 支持自检」
goto :TGPU_END
:TGPU_REQ
call :GPU_PROBE
if "%GPU_AVAILABLE%"=="1" (
  echo         正常    %GPU_NAME%
  echo                 显存 %GPU_TOTAL_MIB% MiB 总 / %GPU_FREE_MIB% MiB 空闲，本次将启用 GPU 混合卸载
) else (
  echo         提示    未启用 GPU，本次按纯 CPU 运行（默认兜底，不是错误）
  echo                 %GPU_PROBE_NOTE%
  echo                 排查：跑 环境检查.bat 看第 11 项「GPU 支持自检」
)
:TGPU_END
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
