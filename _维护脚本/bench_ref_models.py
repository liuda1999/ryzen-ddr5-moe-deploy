#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""对指定模型做同口径短上下文生成测速，用于回答「MTP / 多模态是否拖慢基线」。

用法：
  python bench_ref_models.py <模型路径> [模型路径 ...]
每个模型：用项目最优 GPU 参数起服务 -> 等就绪 -> 短提示测 3 轮 -> 关服务。
"""
import sys, os, time, json, subprocess, urllib.request, urllib.error, shutil, signal

PORT = 35100
BIN = "E:/llm-cpp/llama.cpp/build-zen5/bin/llama-server.exe"
NGL = os.environ.get("NGL", "40")
COMMON = [
    "--host", "127.0.0.1", "--port", str(PORT),
    "--ctx-size", "16384", "--parallel", "1",
    "-ngl", NGL, "--cpu-moe",
    "-t", "24",
]
ASK = "请用简洁的中文解释一下什么是 MoE 混合专家模型，它在推理时为什么比稠密模型省算力，并举一个生活中的类比。"

def wait_ready(timeout=240):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            with urllib.request.urlopen("http://127.0.0.1:%d/health" % PORT, timeout=5) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(2)
    return False

def measure():
    payload = {"prompt": ASK, "n_predict": 256, "temperature": 0.0,
               "top_k": 1, "cache_prompt": False}
    req = urllib.request.Request(
        "http://127.0.0.1:%d/completion" % PORT,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        d = json.loads(r.read().decode("utf-8"))
    return d.get("timings", {})

def bench(model):
    print("\n===== 测速：%s =====" % os.path.basename(model), flush=True)
    args = [BIN] + COMMON + ["-m", model]
    p = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        if not wait_ready():
            print("  [失败] 服务未在时限内就绪", flush=True)
            return None
        res = []
        for i in range(3):
            try:
                tm = measure()
                gen = tm.get("predicted_per_second")
                pre = tm.get("prompt_per_second")
                print("  轮 %d: 生成 %.2f t/s | prefill %.1f t/s | 生成 %d tok" % (
                    i + 1, gen or 0, pre or 0, tm.get("predicted_tokens", 0)), flush=True)
                if gen:
                    res.append(gen)
            except Exception as e:
                print("  轮 %d 出错: %s" % (i + 1, e), flush=True)
        if res:
            res.sort()
            med = res[len(res) // 2]
            print("  --> 中位数 %.2f t/s（3 轮：%s）" % (med, ", ".join("%.2f" % x for x in res)), flush=True)
            return med
    finally:
        p.terminate()
        try:
            p.wait(timeout=20)
        except Exception:
            p.kill()
        time.sleep(2)
    return None

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python bench_ref_models.py <模型路径> [...]")
        sys.exit(1)
    out = {}
    for m in sys.argv[1:]:
        if not os.path.exists(m):
            print("文件不存在: %s" % m, flush=True)
            continue
        out[os.path.basename(m)] = bench(m)
    print("\n========== 汇总 ==========")
    for k, v in out.items():
        print("  %-55s %s" % (k, ("%.2f t/s" % v) if v else "失败/跳过"))
