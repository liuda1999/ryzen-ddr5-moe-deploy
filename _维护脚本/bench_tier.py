#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""上下文档位测速台架：指定模型 + -c 上下文，起服务、抓显存分解、测速。

用法示例：
  python bench_tier.py --model M.gguf --ctx 32768 --ngl 40 --threads 24
  python bench_tier.py --model M.gguf --ctx 32768 --no-mmproj --modes short,full
输出：
  - 显存分解（model / KV / compute buffer，来自服务启动日志）
  - short：短提示生成速度；full：把上下文填到 ~90% 后的生成速度
"""
import os, time, json, argparse, subprocess, urllib.request

BIN = "E:/llm-cpp/llama.cpp/build-zen5/bin/llama-server.exe"
MMPROJ = "E:/llm-cpp/llama.cpp/models/mmproj-BF16.gguf"
LOGDIR = "E:/llm-cpp/logs"
ASK = "请用简洁的中文解释一下什么是 MoE 混合专家模型，它在推理时为什么比稠密模型省算力，并举一个生活中的类比。"
FILL = ("下面是一段用于填充上下文的说明文字，内容本身不重要，仅用于测试长上下文下的推理性能。"
        "混合专家模型在每一层放置多个前馈子网络，推理时只激活其中少数几个，从而在参数量很大时把计算量控制住。\n")


def build_prompt(mode, ctx):
    if mode == "short":
        return ASK
    target_chars = int(ctx * 0.9 * 1.5)   # 中文约 1.6 字符/token，取 1.5 保守
    reps = max(1, target_chars // max(1, len(FILL)))
    return FILL * reps + "\n\n" + ASK


def parse_buffers(logpath):
    out = {}
    try:
        t = open(logpath, encoding="utf-8", errors="replace").read()
    except Exception:
        return out
    for line in t.splitlines():
        for key in ["model buffer size", "KV buffer size", "compute buffer size"]:
            if key in line and "CUDA0" in line and key not in out:
                out[key] = line.split("=")[-1].strip()
    return out


def wait_ready(port, timeout):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            with urllib.request.urlopen("http://127.0.0.1:%d/health" % port, timeout=5) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(3)
    return False


def measure(port, prompt, rounds):
    res, last = [], {}
    for _ in range(rounds):
        payload = {"prompt": prompt, "n_predict": 256, "temperature": 0.0,
                   "top_k": 1, "cache_prompt": False}
        req = urllib.request.Request("http://127.0.0.1:%d/completion" % port,
                                     data=json.dumps(payload).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=1800) as r:
            d = json.loads(r.read().decode("utf-8"))
        tm = d.get("timings", {})
        last = tm
        if tm.get("predicted_per_second"):
            res.append(tm["predicted_per_second"])
    if not res:
        return None, last
    res.sort()
    return res[len(res) // 2], last


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--ctx", type=int, default=32768)
    ap.add_argument("--ngl", type=int, default=40)
    ap.add_argument("--threads", type=int, default=24)
    ap.add_argument("--no-mmproj", action="store_true")
    ap.add_argument("--modes", default="short")
    ap.add_argument("--port", type=int, default=35100)
    ap.add_argument("--rounds", type=int, default=2)
    a = ap.parse_args()

    tag = "%s_c%d_n%d%s" % (os.path.basename(a.model).replace(".gguf", ""),
                            a.ctx, a.ngl, "_nomm" if a.no_mmproj else "")
    logpath = os.path.join(LOGDIR, "ctx_%s.log" % tag)
    os.makedirs(LOGDIR, exist_ok=True)

    args = [BIN, "--host", "127.0.0.1", "--port", str(a.port),
            "--ctx-size", str(a.ctx), "--parallel", "1",
            "-ngl", str(a.ngl), "--cpu-moe", "-t", str(a.threads), "-m", a.model]
    if not a.no_mmproj:
        args += ["--mmproj", MMPROJ]

    print("启动：%s" % os.path.basename(a.model), flush=True)
    print("  参数：-c %d  -ngl %d  -t %d  %s" % (
        a.ctx, a.ngl, a.threads, "无 mmproj" if a.no_mmproj else "含 mmproj"), flush=True)
    logf = open(logpath, "w", encoding="utf-8", errors="replace")
    p = subprocess.Popen(args, stdout=logf, stderr=subprocess.STDOUT)
    try:
        if not wait_ready(a.port, 300):
            print("  [失败] 服务未就绪（可能显存不足/加载失败）", flush=True)
            tail = "".join(open(logpath, encoding="utf-8", errors="replace").read().splitlines(True)[-14:])
            print("  日志尾部：\n%s" % tail, flush=True)
            return
        print("  显存分解：%s" % parse_buffers(logpath), flush=True)
        for mode in a.modes.split(","):
            mode = mode.strip()
            r = a.rounds if mode == "short" else 1
            gen, tm = measure(a.port, build_prompt(mode, a.ctx), r)
            if gen:
                print("  [%s] 生成 %.2f t/s | prefill %.1f t/s | 提示 %d tok | 生成 %d tok" % (
                    mode, gen, tm.get("prompt_per_second", 0),
                    tm.get("prompt_n", 0), tm.get("predicted_n", 0)), flush=True)
            else:
                print("  [%s] 无数据" % mode, flush=True)
    finally:
        p.terminate()
        try:
            p.wait(timeout=20)
        except Exception:
            p.kill()
        logf.close()
        time.sleep(2)


if __name__ == "__main__":
    main()
