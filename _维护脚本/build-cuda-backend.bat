@echo off
REM ============================================================
REM  build-cuda-backend.bat -- build the CUDA backend (ggml-cuda.dll)
REM
REM  Why build it ourselves:
REM    The official llama.cpp nightly Windows CUDA package is 254 MB and
REM    the link to GitHub runs at a few tens of KB/s here, so downloading
REM    is not practical. CUDA Toolkit 12.8 + MSVC 14.44 are already
REM    installed, and the source tree IS the one this project was built
REM    from -- so building locally is actually safer:
REM      1. backend API version matches llama-server by construction
REM      2. same toolchain as the existing binaries (cl 19.44.35225)
REM
REM  Usage: build-cuda-backend.bat [arch]
REM    arch defaults to 61 (GTX 1060 / Pascal). Multiple: 61;75;86
REM
REM  Notes:
REM    - vcvars is blocked in this environment, so PATH/INCLUDE/LIB are
REM      assembled by hand.
REM    - The SDK bin directory must be on PATH: CMake needs rc.exe/mt.exe
REM      when linking, otherwise the compiler check fails with LNK1104.
REM    - Keep this file ASCII-only with CRLF line endings. A UTF-8/LF or
REM      non-ASCII .bat gets mangled by cmd (it parses the file as GBK).
REM ============================================================
setlocal EnableExtensions
set "ARCH=%~1"
if "%ARCH%"=="" set "ARCH=61"

set "MSVC=C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Tools\MSVC\14.44.35207"
set "SDK=C:\Program Files (x86)\Windows Kits\10"
set "SDKVER=10.0.26100.0"
set "CUDA=C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.8"
set "PY=C:\Users\15910\.workbuddy\binaries\python\versions\3.13.12\Scripts"
set "SRC=E:\llm-cpp\llama.cpp"
set "BUILD=E:\llm-cpp\llama.cpp\build-cuda"

set "PATH=%MSVC%\bin\Hostx64\x64;%SDK%\bin\%SDKVER%\x64;%CUDA%\bin;%PY%;%PATH%"
set "INCLUDE=%MSVC%\include;%SDK%\Include\%SDKVER%\ucrt;%SDK%\Include\%SDKVER%\shared;%SDK%\Include\%SDKVER%\um"
set "LIB=%MSVC%\lib\x64;%SDK%\Lib\%SDKVER%\ucrt\x64;%SDK%\Lib\%SDKVER%\um\x64"

echo == compiler ==
REM cl.exe with no arguments reads stdin and never returns (hung for 12 min
REM in testing). Always pass /? and redirect < nul so it prints and exits.
cl.exe /? 2>&1 < nul | findstr /C:"Version"
echo == cuda ==
nvcc.exe --version | findstr /C:"release"

echo.
echo == configure (arch %ARCH%) ==
cmake -S "%SRC%" -B "%BUILD%" -G Ninja ^
  -DCMAKE_BUILD_TYPE=Release ^
  -DBUILD_SHARED_LIBS=ON ^
  -DGGML_BACKEND_DL=ON ^
  -DGGML_CUDA=ON ^
  -DCMAKE_CUDA_ARCHITECTURES=%ARCH% ^
  "-DCUDAToolkit_ROOT=%CUDA%" ^
  -DGGML_CPU_ALL_VARIANTS=OFF -DGGML_NATIVE=OFF ^
  -DLLAMA_BUILD_TESTS=OFF -DLLAMA_BUILD_EXAMPLES=OFF ^
  -DLLAMA_BUILD_TOOLS=OFF -DLLAMA_BUILD_SERVER=OFF
if errorlevel 1 goto :fail

echo.
echo == build target ggml-cuda ==
cmake --build "%BUILD%" --target ggml-cuda -- -j 16
if errorlevel 1 goto :fail

echo.
echo == artifacts ==
dir /b /s "%BUILD%\ggml-cuda*.dll"
echo BUILD_OK
exit /b 0

:fail
echo.
echo BUILD_FAILED
exit /b 1
