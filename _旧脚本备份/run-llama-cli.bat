@echo off
REM ============================================================
REM  llama.cpp 命令行推理（仅 CPU / 不使用显卡）
REM  构建：build-zen5（AVX-512 + VBMI + VNNI 变体，运行时自动择优）
REM  用法：拿到 GGUF 模型后，编辑下方 MODEL 路径再运行
REM ------------------------------------------------------------
REM  线程说明：本机 16 物理核 / 32 逻辑核（SMT 开启）。
REM  不盲目用满 32 逻辑线程：推理时线程过多会因同步开销与内存带宽争用反而变慢。
REM  实测（矩阵基准，详见 CONFIG-TIERS.md / matrix_results.csv）：
REM    24 线程（12 核）在全部档位上生成速度都优于 28 线程 ——
REM    28 线程 prefill 快约 2%，但生成反而慢 0.1~0.2 t/s（MoE 生成阶段是内存带宽瓶颈）。
REM    当前默认 ctx 16K（实用档）；追求极限速度改 CTX=12288，可到 13.28 t/s。
REM ============================================================
setlocal
set LLAMA_DIR=%~dp0llama.cpp
set MODEL=%LLAMA_DIR%\models\Qwen3.6-35B-A3B-UD-Q4_K_XL.gguf
set BIN=%LLAMA_DIR%\build-zen5\bin\llama-cli.exe
set THREADS=24
set CTX=16384

if not exist "%BIN%" (
  echo [ERROR] 找不到 %BIN%
  echo 请先编译（build-from-source.bat）。
  exit /b 1
)
if not exist "%MODEL%" (
  echo [ERROR] 未找到模型：%MODEL%
  echo 请把 GGUF 模型放到 llama.cpp\models\ 目录，并修改本脚本中的 MODEL 变量。
  exit /b 1
)

echo [INFO] 线程数：%THREADS% （12 物理核，实测生成最快档）
echo [INFO] 上下文：%CTX%
echo [INFO] 提示：如需多轮交互对话，把下面命令里的 -st 去掉。

"%BIN%" ^
  --model "%MODEL%" ^
  --prompt "你好，请用一句话介绍你自己。" ^
  -n 256 -st ^
  --ctx-size %CTX% ^
  --threads %THREADS% ^
  --threads-batch %THREADS% ^
  --n-gpu-layers 0
endlocal
