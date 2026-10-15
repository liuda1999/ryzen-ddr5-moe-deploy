@echo off
REM ============================================================
REM  llama.cpp HTTP 服务启动器（仅 CPU / 不使用显卡）
REM  构建：build-zen5（AVX-512 + VBMI + VNNI 变体，运行时自动择优）
REM  用法：拿到 GGUF 模型后，编辑下方 MODEL 路径再运行
REM  启动后提供 OpenAI 兼容 API：http://127.0.0.1:8080/v1/chat/completions
REM ------------------------------------------------------------
REM  线程说明：本机 16 物理核 / 32 逻辑核（SMT 开启）。
REM  服务常驻场景下不占满 32 逻辑线程，避免系统与其他任务争抢，
REM  实测（矩阵基准，详见 CONFIG-TIERS.md / matrix_results.csv）：
REM    24 线程（12 核）在全部档位上生成速度都优于 28 线程 ——
REM    28 线程 prefill 快约 2%，但生成反而慢 0.1~0.2 t/s（MoE 生成阶段是内存带宽瓶颈）。
REM ============================================================
setlocal
set LLAMA_DIR=%~dp0llama.cpp
set MODEL=%LLAMA_DIR%\models\Qwen3.6-35B-A3B-UD-Q4_K_XL.gguf
set MMPROJ=%LLAMA_DIR%\models\mmproj-BF16.gguf
set BIN=%LLAMA_DIR%\build-zen5\bin\llama-server.exe
set THREADS=24
REM 上下文档位（当前默认 16K = 实用档）：
REM   12K 生成最快(13.28 t/s)但容量偏小；16K 慢 4%(12.73 t/s)却多 33% 上下文，综合最实用。
REM   64K/96K 虽能跑，prefill 会掉到 44~60 t/s、单 token 延迟 234~408ms，纯 CPU 下不实用。
REM   全部档位与实测数据见 E:\llm-cpp\CONFIG-TIERS.md
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
if not exist "%MMPROJ%" (
  echo [WARN] 未找到视觉投影：%MMPROJ%，将以纯文本模式启动（不处理图片）
  set MMPROJ_ARG=
) else (
  set MMPROJ_ARG=--mmproj "%MMPROJ%"
)

REM 注意：该模型原生上下文为 262144，若不限会按 262144 分配 KV cache（极易撑爆内存），
REM      故显式限制为 8192（4 个槽位共享，足够中长多轮对话）。
REM      需要更长上下文时改 --ctx-size，并留意内存占用（每翻倍约增加数 GB）。
echo [INFO] 线程数：%THREADS% （16 物理核 / 32 逻辑核，按 14 物理核=28 线程使用，不占满）
echo [INFO] 上下文：%CTX%（已限制，模型原生 262144）

"%BIN%" ^
  --model "%MODEL%" ^
  %MMPROJ_ARG% ^
  --host 127.0.0.1 ^
  --port 8080 ^
  --threads %THREADS% ^
  --threads-batch %THREADS% ^
  --ctx-size %CTX% ^
  --n-gpu-layers 0
endlocal
