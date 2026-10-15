#!/bin/bash
# ============================================================
#  上下文 × 线程 组合基准（8 组）
#  ctx:     12288 / 13312 / 14336 / 16384  (12K/13K/14K/16K)
#  threads: 24 (12核) / 28 (14核)
#  评判指标：生成速度 (tokens/s)
# ============================================================
MSVC_BIN="/c/Program Files/Microsoft Visual Studio/2022/Community/VC/Tools/MSVC/14.44.35207/bin/Hostx64/x64"
SDK_BIN="/c/Program Files (x86)/Windows Kits/10/bin/10.0.26100.0/x64"
export PATH="$MSVC_BIN:$SDK_BIN:$PATH"
export INCLUDE="C:/Program Files/Microsoft Visual Studio/2022/Community/VC/Tools/MSVC/14.44.35207/include;C:/Program Files (x86)/Windows Kits/10/Include/10.0.26100.0/ucrt;C:/Program Files (x86)/Windows Kits/10/Include/10.0.26100.0/um;C:/Program Files (x86)/Windows Kits/10/Include/10.0.26100.0/shared"
export LIB="C:/Program Files/Microsoft Visual Studio/2022/Community/VC/Tools/MSVC/14.44.35207/lib/x64;C:/Program Files (x86)/Windows Kits/10/Lib/10.0.26100.0/ucrt/x64;C:/Program Files (x86)/Windows Kits/10/Lib/10.0.26100.0/um/x64"

PY=/c/Users/15910/.workbuddy/binaries/python/versions/3.13.12/python.exe
BIN=/e/llm-cpp/llama.cpp/build-zen5/bin/llama-server.exe
MODEL="E:/llm-cpp/llama.cpp/models/Qwen3.6-35B-A3B-UD-Q4_K_XL.gguf"
MMPROJ="E:/llm-cpp/llama.cpp/models/mmproj-BF16.gguf"
LOG=/e/llm-cpp/srv_matrix.log
OUT=${OUT:-/e/llm-cpp/matrix_results.csv}
GEN=${GEN:-384}

CTXS=${CTXS:-"12288 13312 14336 16384"}
THREADS=${THREADS:-"24 28"}

echo "ctx,threads,pp_tokens,pp_tps,gen_tokens,gen_tps,wall_s" > "$OUT"

for T in $THREADS; do
  for C in $CTXS; do
    echo "=============================================================="
    echo "[组合] ctx=$C  threads=$T   $(date +%H:%M:%S)"
    echo "=============================================================="

    rm -f "$LOG"
    "$BIN" -m "$MODEL" --mmproj "$MMPROJ" \
      -t $T -tb $T -ngl 0 -c $C \
      --host 127.0.0.1 --port 8080 > "$LOG" 2>&1 &
    SRVPID=$!

    # 等待服务就绪
    READY=0
    for i in $(seq 1 150); do
      if curl -s --noproxy 127.0.0.1 --max-time 3 http://127.0.0.1:8080/health 2>/dev/null | grep -q '"ok"'; then
        READY=1; break
      fi
      sleep 2
    done

    if [ $READY -ne 1 ]; then
      echo "$C,$T,ERROR,server-not-ready,0,0,0" >> "$OUT"
      kill -9 $SRVPID 2>/dev/null
      continue
    fi
    echo "  服务就绪，开始基准 $(date +%H:%M:%S)"

    PYTHONPATH= "$PY" /e/llm-cpp/bench_ctx.py $C $GEN $T "$LOG" | tee -a "$OUT"

    kill -9 $SRVPID 2>/dev/null
    sleep 6
  done
done

echo "=============================================================="
echo "[矩阵测试完成] $(date +%H:%M:%S)"
cat "$OUT"
