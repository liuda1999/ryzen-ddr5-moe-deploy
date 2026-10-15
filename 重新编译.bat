@echo off
REM ============================================================
REM  llama.cpp 重编译（仅 CPU / 不使用显卡）
REM  目标：构建全部 x86 CPU 变体，运行时自动择优命中 AVX-512 + VBMI + VNNI
REM  适用：在你自己的 Windows 上重新编译时使用（Visual Studio 生成器）
REM  产物：build-vs\bin\Release\
REM ============================================================
setlocal
set LLAMA_DIR=%~dp0llama.cpp
set BIN=%LLAMA_DIR%\build-vs\bin\Release

REM 1) 配置 MSVC (x64) 环境
call "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvarsall.bat" x64
if errorlevel 1 (
  echo [ERROR] 未找到 vcvarsall.bat，请确认已安装 VS2022 的“使用 C++ 的桌面开发”工作负载。
  exit /b 1
)

REM 2) CMake 配置
REM    - 全部 CPU 变体（GGML_CPU_ALL_VARIANTS）是启用 AVX-512 扩展（VNNI/VBMI）的唯一途径：
REM      直接传 -DGGML_AVX512_VNNI=ON 会被 CMake 的变体函数重置为 OFF，无效。
REM    - 变体以动态后端加载，因此需要 BUILD_SHARED_LIBS=ON + GGML_BACKEND_DL=ON。
cmake -S "%LLAMA_DIR%" -B "%LLAMA_DIR%\build-vs" -G "Visual Studio 17 2022" -A x64 ^
  -DCMAKE_BUILD_TYPE=Release ^
  -DBUILD_SHARED_LIBS=ON -DGGML_BACKEND_DL=ON ^
  -DGGML_CPU_ALL_VARIANTS=ON -DGGML_NATIVE=OFF ^
  -DGGML_CUDA=OFF -DGGML_VULKAN=OFF -DGGML_OPENCL=OFF -DGGML_METAL=OFF -DGGML_HIP=OFF ^
  -DLLAMA_OPENSSL=OFF ^
  -DLLAMA_BUILD_UI=OFF -DLLAMA_USE_PREBUILT_UI=OFF ^
  -DLLAMA_BUILD_SERVER=ON -DLLAMA_BUILD_EXAMPLES=OFF -DLLAMA_BUILD_TESTS=OFF
if errorlevel 1 ( echo [ERROR] CMake 配置失败 & exit /b 1 )

REM 3) 编译
cmake --build "%LLAMA_DIR%\build-vs" --config Release -j
if errorlevel 1 ( echo [ERROR] 编译失败 & exit /b 1 )

REM 4) 让 icelake 变体（AVX-512 + VBMI + VNNI）成为最优先
REM    原因：上游对 VBMI 只定义了 __AVX512VBMI__（启用代码路径），
REM          未定义参与评分的 GGML_AVX512_VBMI，导致 icelake 与 cascadelake 同分，
REM          而 cascadelake 按字母序先命中（不含 VBMI）。
REM    处理：将 cascadelake 改名为 .disabled（不删除，可随时改回）。
REM    前提：CPU 需支持 VBMI（可用 check-cpuid.exe 确认，VBMI=1 才做此步）。
REM    注意：换到 Intel 平台时，若该 CPU 支持 AVX-512 但不支持 VBMI
REM          （如 Cascade Lake 至强），不要执行这步改名，否则会掉到更低变体。
if exist "%BIN%\ggml-cpu-cascadelake.dll" (
  ren "%BIN%\ggml-cpu-cascadelake.dll" ggml-cpu-cascadelake.dll.disabled
  echo [INFO] 已停用 cascadelake 变体，优先使用 icelake（AVX-512 + VBMI + VNNI）
)

echo.
echo [OK] 产物：%BIN%
echo   llama-cli.exe / llama-server.exe / llama-bench.exe
echo   验证：在该目录运行 verify-isa.exe，应显示 AVX512=1 / AVX512_VBMI=1 / AVX512_VNNI=1
endlocal
