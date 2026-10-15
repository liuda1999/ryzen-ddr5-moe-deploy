# -*- coding: utf-8 -*-
"""生成中文命名的环境与安全检查脚本（GBK + CRLF）。"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "环境检查_EnvCheck.bat")

BAT = r'''@echo off
REM 注意 <nul：chcp 改代码页时会读并清空输入缓冲，重定向/管道送 stdin
REM 的场景下会把第一行输入吞掉（实测），加 <nul 让它立刻读到 EOF。
chcp 936 <nul >nul 2>nul
setlocal EnableExtensions
title Qwen3.6-35B 本地大模型 环境与安全检查

REM ============================================================
REM   环境检查_EnvCheck.bat —— 启动前的全量体检
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
echo   Qwen3.6-35B 本地大模型 / Local LLM · 环境与安全检查 / Environment and safety check
echo ============================================================
echo.

echo [1/11] 可执行程序 / Executables
call :CHK_FILE "%BIN_DIR%\llama-server.exe"
call :CHK_FILE "%BIN_DIR%\llama-cli.exe"
call :CHK_FILE "%BIN_DIR%\llama-bench.exe"
echo.

echo [2/11] 依赖动态库 / Runtime DLLs
call :CHK_FILE "%BIN_DIR%\llama.dll"
call :CHK_FILE "%BIN_DIR%\llama-common.dll"
call :CHK_FILE "%BIN_DIR%\ggml.dll"
call :CHK_FILE "%BIN_DIR%\ggml-base.dll"
echo         运行库 / runtime（随包附带 / bundled，目标机无需安装 / no VC++ Redist needed）
call :CHK_FILE "%BIN_DIR%\vcruntime140.dll"
call :CHK_FILE "%BIN_DIR%\msvcp140.dll"
call :CHK_FILE "%BIN_DIR%\vcomp140.dll"
echo.

echo [3/11] CPU 指令集后端 / CPU ISA backend（决定能否用满 AVX-512 / whether AVX-512 is fully used）
call :CHK_FILE "%BIN_DIR%\ggml-cpu-icelake.dll"
if not exist "%BIN_DIR%\ggml-cpu-icelake.dll" goto :PISA_NONE
if exist "%BIN_DIR%\ggml-cpu-cascadelake.dll" (
  echo         [警告/WARN] ggml-cpu-cascadelake.dll 处于启用状态 / is enabled
  echo                它会抢在 icelake 之前被选中 / it would be picked before icelake，导致 VBMI 指令失效 / disabling VBMI
  echo                处理/FIX：启动大模型_StartModel.bat 会自动改名为 .disabled / renames it to .disabled automatically
  set "WARN=1"
) else (
  echo         正常/OK    icelake 变体优先/preferred，AVX-512 + VNNI + VBMI 生效/active
)
goto :PISA_END
:PISA_NONE
echo         提示/HINT  icelake 变体缺失/missing，需重新编译补齐 / rebuild to add it（见上方 [失败] 项 / see the FAIL item above）
:PISA_END
echo.

echo [4/11] 模型文件 / Model file
if not exist "%MODEL%" set "MODEL_MISS=1"
call :CHK_FILE "%MODEL%"
if exist "%MODEL%" (
  REM 注意：这里必须在 for 体内直接用 %%a 输出。若先 set 再 echo，由于括号块内的
  REM       %VAR% 在整块解析时就展开，会拿到空值（踩过一次的坑）。
  for /f "usebackq delims=" %%a in (`powershell -NoProfile -Command "[math]::Round((Get-Item -LiteralPath '%MODEL%').Length/1GB,2)"`) do echo         大小/Size %%a GB（Q4 级别完整约 20 GB / a full Q4 is about 20 GB，明显偏小说明文件损坏 / much smaller means corrupt）
) else (
  echo         下载地址见 / download links in README.md 的「模型下载」一节 / Model download section
  echo         或本机文件 / or the local file llama.cpp\models\下载模型.md
  echo         下载后保持文件名不变 / keep the filename unchanged，放入/put it into llama.cpp\models\
)
echo.

echo [5/11] 视觉投影 / Vision projector（多模态/multimodal，缺失不影响纯文本 / optional for text）
if exist "%MMPROJ%" (
  echo         正常/OK    mmproj-BF16.gguf
) else (
  echo         [警告/WARN] 未找到 mmproj / not found，将只能处理纯文本 / text-only
  set "WARN=1"
)
echo.

echo [6/11] 端口/Port %PORT% 状态 / status
call :PORT_STATE
if "%PSTATE%"=="free" goto :P6_FREE
call :GET_OWNER
echo         占用中/IN USE  PID %PPID% （%PNAME%）
goto :P6_END
:P6_FREE
echo         正常/OK    端口空闲 / port free，可以启动 / ready to start
:P6_END
echo.

echo [7/11] 内存与档位可行性 / Memory and tier feasibility
for /f "usebackq delims=" %%a in (`powershell -NoProfile -Command "[int]((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory/1024)"`) do set "FREE_MB=%%a"
for /f "usebackq delims=" %%a in (`powershell -NoProfile -Command "[int]((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory/1GB)"`) do set "TOTAL_GB=%%a"
set /a FREE_GB=%FREE_MB% / 1024
echo         物理总内存 / physical RAM %TOTAL_GB% GB，当前可用/free %FREE_GB% GB
echo.
call :TIER_LINE 1 实用档     16384 24 24
call :TIER_LINE 2 长文档档   24576 24 24
call :TIER_LINE 3 超长档     32768 24 25
call :TIER_LINE 4 长上下文档 65536 24 25
call :TIER_LINE 5 超大档     98304 24 26
call :TIER_LINE 6 极限档    131072 24 26
call :DETECT_SRV
if defined SRV_PID echo         ^(提示：当前已有服务在运行并占用内存，故上面的可用性判断会偏保守^)
echo.

echo [8/11] 磁盘与日志目录 / Disk and log folder
set "DL=%ROOT:~0,1%"
for /f "usebackq delims=" %%a in (`powershell -NoProfile -Command "[int]((Get-PSDrive -Name '%DL%').Free/1GB)"`) do set "DISK_GB=%%a"
if %DISK_GB% LSS 2 (
  echo         [失败/FAIL]  %DL%: 盘仅剩/only %DISK_GB% GB，无法写日志 / cannot write logs
  set "FAIL=1"
) else (
  echo         正常/OK    %DL%: 盘剩余/free %DISK_GB% GB
)
if exist "%LOG_DIR%" (
  echo         正常/OK    日志目录/log folder %LOG_DIR%
) else (
  echo         提示/HINT    日志目录尚未创建 / log folder not created yet，首次启动服务时会自动建立 / created on first start
)
if exist "%SystemRoot%\System32\curl.exe" (
  echo         正常/OK    系统自带 curl / built-in curl（用于精确判断服务是否真正加载完成 / for accurate readiness checks）
) else (
  echo         [警告/WARN]  缺少 curl / missing，启动脚本会退化为只检测端口监听 / falls back to port checks only
  set "WARN=1"
)
echo.

echo [9/11] 当前服务状态 / Service status
call :DETECT_SRV
if not defined SRV_PID goto :P9_DOWN
call :GET_MEM
echo         运行中/RUNNING  PID %SRV_PID%，占用/using %SRV_MEM% GB
call :READ_PIDFILE
if defined CUR_TIER echo                 档位 %CUR_TIER% 号，上下文 %CUR_CTX%，线程 %CUR_T%，启动于 %CUR_TIME%
echo                 访问/Open http://127.0.0.1:%PORT%
goto :P9_END
:P9_DOWN
echo         未运行 / not running
if exist "%PID_FILE%" (
  echo         [警告/WARN] 存在残留状态文件 / stale state file %PID_FILE%，下次启动会自动清理 / cleaned on next start
  set "WARN=1"
)
:P9_END

echo.

echo [10/11] 局域网访问 / LAN access
call :GET_LAN_IP
if defined LAN_IP goto :P10_HASIP
echo         [警告/WARN]  未检测到局域网 IPv4 / no LAN IPv4，其它设备可能无法访问 / other devices may not connect
set "WARN=1"
goto :P10_KEY
:P10_HASIP
echo         本机 IP / local IP  %LAN_IP%
echo         入口/URL     http://%LAN_IP%:%PORT%   ^(需携带密钥/key required^)
:P10_KEY
if not exist "%KEY_FILE%" goto :P10_NOKEY
call :LOAD_KEY
if not defined API_KEY goto :P10_EMPTYKEY
echo         正常/OK    访问密钥已就绪 / API key ready %KEY_FILE%
goto :P10_FW
:P10_EMPTYKEY
echo         [警告/WARN]  密钥文件里没有有效密钥 / no valid key，局域网请求会被拒绝 / LAN calls will be rejected
set "WARN=1"
goto :P10_FW
:P10_NOKEY
echo         [警告/WARN]  密钥文件尚未生成 / key file not created yet（首次启动服务时会自动创建 / created on first start）
set "WARN=1"
:P10_FW
netsh advfirewall firewall show rule name="llama.cpp-%PORT%" >nul 2>&1
if not errorlevel 1 goto :P10_FWOK
echo         [警告/WARN]  未发现防火墙放行规则 / no firewall rule，局域网设备可能连不上 / other devices may not connect
echo                 需用管理员身份执行一次 / run once as administrator：
echo                 netsh advfirewall firewall add rule name="llama.cpp-%PORT%" dir=in action=allow protocol=TCP localport=%PORT%
goto :P10_END
:P10_FWOK
echo         正常/OK    防火墙已放行 / firewall rule allows TCP %PORT%
:P10_END
echo.

REM ============================================================
REM  [11] GPU 支持自检（只针对 NVIDIA 独立显卡）
REM
REM  这一项全部按「警告」处理，绝不设 [失败] —— 因为 GPU 不可用时
REM  服务仍会以纯 CPU 正常运行，不该因为显卡问题阻止启动。
REM  GPU_MODE 默认就是 auto，所以「GPU 用不上」只是回到纯 CPU 兜底，
REM  属于正常路径，本项只负责说清缺什么、怎么补。
REM  核显、AMD / Intel 显卡一律按纯 CPU 处理，不在检查范围内。
REM ============================================================
echo [11/11] GPU 支持自检 / GPU support check（只针对 NVIDIA 独立显卡 / NVIDIA discrete GPUs only）
powershell -NoProfile -Command "$a=Get-CimInstance Win32_VideoController -ErrorAction SilentlyContinue; foreach($v in $a){ if($v.Name -match 'NVIDIA'){ Write-Output $v.Name } }" > "%TEMP%\llm_nv_name.txt" 2>nul
set "NV_NAME="
if exist "%TEMP%\llm_nv_name.txt" (
  for /f "usebackq delims=" %%a in ("%TEMP%\llm_nv_name.txt") do if not defined NV_NAME set "NV_NAME=%%a"
  del "%TEMP%\llm_nv_name.txt" >nul 2>nul
)
if not defined NV_NAME goto :P11_NONV
echo         正常/OK    检测到 N 卡 / NVIDIA GPU found：%NV_NAME%
if exist "%SystemRoot%\System32\nvcuda.dll" (
  echo         正常/OK    CUDA 驱动层 nvcuda.dll 存在 / driver layer present
) else (
  echo         [警告/WARN]  未找到 nvcuda.dll / not found，NVIDIA 驱动可能未正确安装 / driver may be missing
  echo                 请到 NVIDIA 官网安装或更新显卡驱动 / install or update the NVIDIA driver
  set "WARN=1"
)
set "CUDA_LIB_MISS="
call :CHK_CUDA_LIB cublas64_12.dll
call :CHK_CUDA_LIB cublasLt64_12.dll
call :CHK_CUDA_LIB cudart64_12.dll
if defined CUDA_LIB_MISS goto :P11_GUIDE
goto :P11_BACKEND
:P11_GUIDE
set "WARN=1"
echo.
echo         CUDA 运行库是显卡驱动之外的另一套库 / CUDA runtime libraries are separate from the driver，只装驱动不会自带 / the driver alone does not include them.
echo         三种取法，按推荐顺序 / three ways, in order of preference：
echo           1  复用本机已有的 / reuse what you already have
echo              装过 CUDA、跑过 PyTorch 的机器通常已有这几个 DLL / machines with CUDA or PyTorch usually have them，
echo              把它们的目录加入 PATH 即可 / just add their folder to PATH，不必复制文件 / no copying needed.
echo           2  只取需要的 3 个 DLL / grab only the 3 needed DLLs，约/~400~500 MB
echo              pip download nvidia-cublas-cu12 nvidia-cuda-runtime-cu12 -d .
echo              解包后把 / after unpacking, take cublas64_12.dll / cublasLt64_12.dll / cudart64_12.dll
echo              放进/copy into llama.cpp\build-zen5\bin\
echo           3  安装官方 CUDA Toolkit 12.8 / install the official toolkit，约/~3 GB，可只勾 Runtime 组件 / Runtime component only
echo         注意/NOTE：必须是 12.x 系列 / must be 12.x。CUDA 13.0 起已不支持 Maxwell / Pascal / Volta 旧卡 / drops old-arch support.
:P11_BACKEND
if not exist "%BIN_DIR%\ggml-cuda.dll" goto :P11_NOBACKEND
echo         正常/OK    CUDA 后端 ggml-cuda.dll 存在 / present
call :P11_PROBE
goto :P11_END
:P11_NOBACKEND
echo         [警告/WARN]  未找到 CUDA 后端 / ggml-cuda.dll not found（可选组件 / optional）
echo                 它是可选的 / it is optional：不带它服务照样跑 / the service still runs，只是 N 卡加速用不上 / just no GPU speed-up，
echo                 启动时会自动按纯 CPU 运行 / it falls back to CPU-only. 它不是显卡驱动 / it is not the GPU driver，而是 / but
echo                 llama.cpp 的 CUDA 后端文件 / the llama.cpp CUDA backend. 两种取法 / two ways to get it：
echo                   1  本机自编 / build locally：_维护脚本\build-cuda-backend.bat 61
echo                      （61 = Pascal；按自己显卡的代际填 / use your GPU architecture，产物约/~32 MB）
echo                   2  下载 llama.cpp 官方 Windows CUDA 预编译包 / download the official prebuilt package，取出 / and extract
echo                      其中的 ggml-cuda.dll / the file named ggml-cuda.dll
echo                 放进/copy into llama.cpp\build-zen5\bin\
echo                 要求/REQUIREMENT：后端 API 版本须与本项目一致 / backend API version must match，否则会被拒绝加载 / otherwise it is rejected
echo                 并自动退回纯 CPU / and it falls back to CPU. 放好后重跑本检查即可确认 / re-run this check to confirm.
set "WARN=1"
goto :P11_END
:P11_NONV
echo         提示/HINT    未检测到 NVIDIA 独立显卡 / no NVIDIA GPU found（按系统设备列表判断 / from the device list）
if not exist "%BIN_DIR%\ggml-cuda.dll" goto :P11_NONV_END
echo                 不过库里已有 CUDA 后端 / but the CUDA backend exists，再做一次后端实测确认 / running a live device probe：
call :P11_PROBE
:P11_NONV_END
echo                 按纯 CPU 运行即可 / CPU-only is fine —— 这是正常情况 / this is normal，无需处理 / nothing to do.
echo                 核显与 AMD / Intel 显卡同样按纯 CPU 处理 / integrated and AMD/Intel GPUs also run CPU-only.
:P11_END
echo.
echo ============================================================
if "%FAIL%"=="1" (
  echo   结论/RESULT：检查未通过 / checks failed（有 [失败] 项 / FAIL items），请先修复后再启动 / fix them first.
  if not exist "%BIN_DIR%\llama-server.exe" echo         缺少程序时：运行 重新编译_Rebuild.bat 重新编译
  if "%MODEL_MISS%"=="1" echo         缺少模型时：按 README.md「模型下载」下载后放入 llama.cpp\models\
) else (
  if "%WARN%"=="1" (
    echo   结论/RESULT：可以启动 / can start，但有 [警告] 项 / with warnings，建议留意上面提示 / mind the notes above.
  ) else (
    echo   结论/RESULT：全部通过 / all good，可以启动 / ready to start.
  )
  echo         启动命令 / start with：启动大模型_StartModel.bat
)
echo ============================================================
echo.
pause
endlocal
exit /b 0

REM ============================================================
:CHK_FILE
if exist "%~1" (
  echo         正常/OK    %~nx1
) else (
  echo         [失败/FAIL]  缺少/missing %~1
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
  echo         不可用/NOT OK 档位/tier %~1 %~2  %~3 ctx / %~4 线程/threads  需/needs %~5 GB  内存不足 / not enough RAM
) else (
  if %FREE_MB% LSS %WARNLVL% (
    echo         紧张/TIGHT 档位/tier %~1 %~2  %~3 ctx / %~4 线程/threads  需/needs %~5 GB
  ) else (
    echo         可用/OK   档位/tier %~1 %~2  %~3 ctx / %~4 线程/threads  需/needs %~5 GB
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

REM ============================================================
REM  子程序：检查一个 CUDA 运行库是否存在
REM
REM  查找顺序与 Windows 的 DLL 搜索顺序一致：先看 exe 同目录 bin\，
REM  再看 PATH。也就是说把 CUDA 的 bin 目录加进 PATH 同样有效，
REM  不必把文件复制过来。
REM  找不到时设置 CUDA_LIB_MISS=1，由调用方汇总成一条警告。
REM ============================================================
:CHK_CUDA_LIB
set "CL_FOUND="
if exist "%BIN_DIR%\%~1" set "CL_FOUND=%BIN_DIR%\%~1"
if not defined CL_FOUND (
  for /f "usebackq delims=" %%a in (`where %~1 2^>nul`) do if not defined CL_FOUND set "CL_FOUND=%%a"
)
if defined CL_FOUND (
  echo         正常/OK    %~1
  echo                 位置/LOCATION %CL_FOUND%
) else (
  echo         [警告/WARN]  缺少/missing %~1
  set "CUDA_LIB_MISS=1"
)
exit /b 0

REM ============================================================
REM  子程序：GPU 后端实测
REM
REM  前面几步只能说明「系统里有 N 卡、文件也在」，但那只代表条件具备；
REM  只有后端自己列得出设备，才等于「llama.cpp 真的能用它」。
REM  所以这里跑一次 llama-server --list-devices 作为最终判定。
REM
REM  解析形如：  CUDA0: NVIDIA GeForce GTX 1660 (6144 MiB, 5312 MiB free)
REM  无设备时后端只会打印「  (none)」，匹配不上，正好判空。
REM ============================================================
:P11_PROBE
set "P11TMP=%TEMP%\llm_check_gpu.txt"
"%BIN_DIR%\llama-server.exe" --list-devices > "%P11TMP%" 2>&1
REM 必须改回代码页：llama-server 会在 common_init() 里
REM SetConsoleOutputCP(CP_UTF8)，把本控制台从 936 改成 65001，
REM 不改回来的话本脚本后面所有 GBK 中文都会变成乱码（已实测）。
call :CP_RESET
set "P11DEV="
for /f "usebackq delims=" %%a in (`powershell -NoProfile -Command "$t=Get-Content -LiteralPath '%P11TMP%' -ErrorAction SilentlyContinue; foreach($l in $t){ if($l -match '^\s*([^:\s]+)\s*:\s*(.+?)\s*\((\d+)\s*MiB,\s*(\d+)\s*MiB free\)'){ Write-Output ($matches[1] + '|' + $matches[2] + '|' + $matches[3] + '|' + $matches[4]); break } }"`) do set "P11DEV=%%a"
del "%P11TMP%" >nul 2>nul
if not defined P11DEV goto :P11_PROBE_FAIL
for /f "tokens=1,2,3,4 delims=|" %%a in ("%P11DEV%") do (
  echo         正常/OK    后端实测可用 / backend works：%%b
  echo                 设备/device %%a，显存/VRAM %%c MiB 总/total / %%d MiB 空闲/free
  echo                 默认已启用 / enabled by default（GPU_MODE=auto）：启动时自动按显存算卸载层数 / layer count computed from VRAM
)
exit /b 0
:P11_PROBE_FAIL
echo         [警告/WARN]  后端实测未列出任何设备 / the live probe listed no devices
echo                 说明 / means llama.cpp cannot use this GPU now；服务仍会以纯 CPU 正常 / the service still runs CPU-only
echo                 运行 / （GPU_MODE=auto 会自动兜底 / auto fallback，不拦启动 / never blocks startup）. 常见成因 / usual causes：
echo                   显卡驱动过老 / outdated GPU driver
echo                   CUDA 运行库与后端版本不匹配 / CUDA runtime vs backend mismatch
echo                   后端 API 版本与本项目不一致 / backend API version mismatch（会被拒绝加载 / rejected on load）
echo                 看原始输出确认 / check the raw output：
echo                   llama.cpp\build-zen5\bin\llama-server.exe --list-devices
set "WARN=1"
exit /b 0

REM ============================================================
REM  子程序：把控制台代码页改回 936
REM  同上：在控制台里跑过 llama-server 之后必须调用。
REM ============================================================
:CP_RESET
chcp 936 <nul >nul 2>nul
exit /b 0
'''

with open(OUT, 'wb') as f:
    f.write(BAT.replace('\n', '\r\n').encode('gbk', errors='strict'))
print("written:", OUT, os.path.getsize(OUT), "bytes")
