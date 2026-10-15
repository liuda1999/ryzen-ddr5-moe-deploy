@echo off
REM ============================================================
REM  llama.cpp 启动前自检 —— 检查产物 / 依赖 / 变体 / 模型 是否齐全
REM  用法：check-env.bat   （或直接双击）
REM  任何一项 FAIL 都意味着启动会失败，按提示处理即可。
REM ============================================================
setlocal

set ROOT=%~dp0
set BIN_DIR=%ROOT%llama.cpp\build-zen5\bin
set MODEL=%ROOT%llama.cpp\models\Qwen3.6-35B-A3B-UD-Q4_K_XL.gguf
set MMPROJ=%ROOT%llama.cpp\models\mmproj-BF16.gguf

set FAIL=0

echo ============================================================
echo   llama.cpp 启动前自检
echo ============================================================
echo.

echo [1] 核心可执行文件
call :CHECK_FILE "%BIN_DIR%\llama-server.exe"
call :CHECK_FILE "%BIN_DIR%\llama-cli.exe"
call :CHECK_FILE "%BIN_DIR%\llama-bench.exe"
echo.

echo [2] 运行依赖 DLL
call :CHECK_FILE "%BIN_DIR%\llama.dll"
call :CHECK_FILE "%BIN_DIR%\llama-common.dll"
call :CHECK_FILE "%BIN_DIR%\ggml.dll"
call :CHECK_FILE "%BIN_DIR%\ggml-base.dll"
echo.

echo [3] CPU 后端变体（AVX-512 关键）
call :CHECK_FILE "%BIN_DIR%\ggml-cpu-icelake.dll"
if exist "%BIN_DIR%\ggml-cpu-cascadelake.dll" (
  echo   WARN  ggml-cpu-cascadelake.dll 仍处于启用状态
  echo         它会抢在 icelake 之前被选中，导致 VBMI 失效。
  echo         建议改名为 ggml-cpu-cascadelake.dll.disabled
) else (
  echo   OK    cascadelake 已让位，icelake ^(AVX-512+VNNI+VBMI^) 将生效
)
echo.

echo [4] 模型文件
call :CHECK_FILE "%MODEL%"
call :CHECK_FILE "%MMPROJ%"
echo.

echo [5] 当前默认配置
for /f "tokens=2 delims==" %%a in ('findstr /b /c:"set CTX=" "%ROOT%run-llama-server.bat"') do set CUR_CTX=%%a
for /f "tokens=2 delims==" %%a in ('findstr /b /c:"set THREADS=" "%ROOT%run-llama-server.bat"') do set CUR_T=%%a
echo   上下文 = %CUR_CTX%      线程 = %CUR_T%
echo   （档位对照见 CONFIG-TIERS.md；修改请编辑 run-llama-server.bat）
echo.

echo [6] 8080 端口占用
netstat -ano | findstr ":8080" | findstr "LISTENING" >nul 2>&1
if errorlevel 1 (
  echo   OK    端口空闲，可以启动
) else (
  echo   占用中 —— 已有服务在跑，直接访问 http://127.0.0.1:8080 即可
  netstat -ano | findstr ":8080" | findstr "LISTENING"
)
echo.

echo ============================================================
if "%FAIL%"=="0" (
  echo   自检通过，可以启动：llm.bat
) else (
  echo   自检未通过，存在 FAIL 项，请先修复。
)
echo ============================================================
echo.
pause
endlocal
exit /b 0

:CHECK_FILE
if exist "%~1" (
  echo   OK    %~nx1
) else (
  echo   FAIL  %~1  缺失
  set FAIL=1
)
exit /b 0
