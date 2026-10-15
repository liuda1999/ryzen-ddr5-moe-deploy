#!/usr/bin/env bash
# GPU 混合卸载基准矩阵（llama-bench，控制变量对比）
#
# 用法：bash bench-gpu-matrix.sh
# 输出：E:/llm-cpp-gpu-test/gpu_matrix.csv
#
# 关键背景（本机实测）：GTX 1060 3GB，总 3071 MiB，空闲仅 2460 MiB（桌面占了 392）。
# 本模型每层约 496 MiB，其中 MoE 专家约 433 MiB、非专家仅约 63 MiB。
#   -> 整层卸载最多放得下约 4 层
#   -> 只卸非专家权重（-ncmoe 让专家留内存）可以放到 30 层以上
# 所以矩阵同时覆盖这两条路线。
#
# llama-bench 参数说明：
#   -ngl N     卸载到 GPU 的层数
#   -ncmoe N   前 N 层的 MoE 专家权重留在内存（>=41 等价于 --cpu-moe）
#   -nkvo 1    KV cache 也留在内存
set -u

BIN="E:/llm-cpp/llama.cpp/build-zen5/bin"
MODEL="E:/llm-cpp/llama.cpp/models/Qwen3.6-35B-A3B-UD-Q4_K_XL.gguf"
OUT="E:/llm-cpp-gpu-test/gpu_matrix.csv"
T=24
: > "$OUT"
echo "tag,ngl,ncmoe,nkvo,pp512,tg128" >> "$OUT"

run() {
  local tag="$1"; local ngl="$2"; local ncmoe="$3"; local nkvo="$4"
  echo "=============================================================="
  echo "  [$tag]  ngl=$ngl  ncmoe=$ncmoe  nkvo=$nkvo"
  echo "=============================================================="
  local out
  out=$("$BIN/llama-bench.exe" -m "$MODEL" -t "$T" -ngl "$ngl" -ncmoe "$ncmoe" -nkvo "$nkvo" \
        -p 512 -n 128 -r 2 2>&1)
  echo "$out" | grep -E "^\|.*(pp512|tg128)" | sed 's/^/  /'
  local pp tg
  pp=$(echo "$out" | grep -E "pp512" | head -1 | awk -F'|' '{print $(NF-1)}' | tr -d ' ')
  tg=$(echo "$out" | grep -E "tg128" | head -1 | awk -F'|' '{print $(NF-1)}' | tr -d ' ')
  echo "  -> pp512=[$pp]  tg128=[$tg]"
  echo "$tag,$ngl,$ncmoe,$nkvo,$pp,$tg" >> "$OUT"
}

# 1) 纯 CPU 基线
run "A-cpu-baseline"    0  0  0
# 2) 只卸非专家权重（专家留内存）—— 本卡的主路线，逐级加层
run "B-ncmoe-ngl8"      8  99 0
run "C-ncmoe-ngl20"    20  99 0
run "D-ncmoe-ngl32"    32  99 0
run "E-ncmoe-ngl41"    41  99 0
# 3) 整层卸载（不区分专家/非专家）
run "F-full-ngl3"       3  0  0
run "G-full-ngl4"       4  0  0

echo
echo "=== 汇总（$OUT）==="
cat "$OUT"
