# -*- coding: utf-8 -*-
"""16K 档位调优台架：逐组参数起一份临时服务，用官方 /completion 的 timings 取真实速度。

用法：
    python tune_16k.py A C D                 # 跑指定几组（默认 short 口径）
    python tune_16k.py --mode full A C       # 用「上下文填满 16K」的严苛口径
    python tune_16k.py --mode short,f/full     # 一次跑两种口径（逗号分隔）

两种口径的区别（速度差别很大，必须写清楚用的是哪个）：
  short —— 约 380 token 的提示，上下文基本为空。相当于「刚开新对话」。
  full  —— 先把约 15.5K token 的提示喂进去，再在满上下文下生成。
           这才是「16K 档位」的真实体感，attention 读 KV 的成本全算进来。

设计要点：
  - 每组都是「起服务 -> 等 /health -> 量 -> 杀进程」，串行，避免抢显存；
  - 端口 35036，与项目正式端口 35035 错开；
  - 速度取 /completion 返回的 timings，不是自己掐表。
"""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BIN = os.path.join(ROOT, "llama.cpp", "build-zen5", "bin")
SERVER = os.path.join(BIN, "llama-server.exe")
MODEL = os.path.join(ROOT, "llama.cpp", "models", "Qwen3.6-35B-A3B-UD-Q4_K_XL.gguf")
MMPROJ = os.path.join(ROOT, "llama.cpp", "models", "mmproj-BF16.gguf")
PORT = 35036
BASE = "http://127.0.0.1:%d" % PORT

ASK = (
    "请用中文写一篇关于本地大模型推理部署的说明，覆盖以下要点："
    "一、为什么消费级硬件上 MoE 模型的瓶颈是内存带宽而不是算力；"
    "二、量化级别对质量与体积的取舍；"
    "三、KV cache 的显存占用如何随上下文线性增长；"
    "四、多线程数与物理核数的关系；"
    "五、Flash Attention 对小显存卡的意义；"
    "六、如何判断一次推理是算力受限还是带宽受限。"
    "请逐条展开，语言平实，不要使用列表符号。"
)

# full 口径用的填充材料（英文散文，token 密度稳定，约 4 字符/token）
FILL = (
    "The deployment of a local language model on consumer hardware is fundamentally "
    "a study in memory bandwidth rather than raw arithmetic throughput. Every token "
    "that the model emits requires the decoder to read the parameters that participate "
    "in that token, and for a mixture of experts architecture only a small fraction of "
    "the parameters are touched per token, which is precisely why such models remain "
    "practical on machines that would otherwise be far too slow. "
)

COMMON = ["-m", MODEL, "--mmproj", MMPROJ, "-c", "16384",
          "--host", "127.0.0.1", "--port", str(PORT), "--parallel", "1",
          "--reasoning", "off"]

# 这些组不加载多模态投影（测它是否有额外开销）
NO_MMPROJ = {"G1", "G2"}

PRESETS = {
    "A": ("基线 -t 24 -ngl 40 --cpu-moe", 24, ["-ngl", "40", "--cpu-moe"]),
    "B": ("A + flash-attn on", 24, ["-ngl", "40", "--cpu-moe", "-fa", "on"]),
    "E": ("A 的线程换 16", 16, ["-ngl", "40", "--cpu-moe"]),
    "F": ("A 的线程换 32", 32, ["-ngl", "40", "--cpu-moe"]),
    "K": ("A 的线程换 40（超配）", 40, ["-ngl", "40", "--cpu-moe"]),
    "L": ("A + KV 量化 q8_0", 24, ["-ngl", "40", "--cpu-moe",
                                   "-ctk", "q8_0", "-ctv", "q8_0"]),
    "M": ("A + 专家显存缓存 128 MiB", 24, ["-ngl", "40", "--cpu-moe",
                                           "--moe-cache-mib", "128"]),
    "N": ("A + mlock（锁内存防换页）", 24, ["-ngl", "40", "--cpu-moe", "--mlock"]),
    "O": ("A + ubatch 1024 / batch 4096", 24, ["-ngl", "40", "--cpu-moe",
                                               "-b", "4096", "-ub", "1024"]),
    "P": ("A + 高优先级 --prio 2", 24, ["-ngl", "40", "--cpu-moe",
                                        "--prio", "2", "--prio-batch", "2"]),
    "Q": ("A + 只绑物理核 -t 16 -C 0-15", 16, ["-ngl", "40", "--cpu-moe",
                                                "-C", "0-15"]),
    "R": ("A 的线程换 20", 20, ["-ngl", "40", "--cpu-moe"]),
    "S": ("A + -ngl 41（把 MTP 层也放上去）", 24, ["-ngl", "41", "--cpu-moe"]),
    "T": ("A + -fa on + KV q8_0", 24, ["-ngl", "40", "--cpu-moe", "-fa", "on",
                                       "-ctk", "q8_0", "-ctv", "q8_0"]),
    "U": ("A + no-mmap", 24, ["-ngl", "40", "--cpu-moe", "--no-mmap"]),
    # ---- 第二轮：还没试过的开关 + CPU 参考基线 ----
    "V": ("A + 拉满轮询 --poll 100", 24, ["-ngl", "40", "--cpu-moe", "--poll", "100"]),
    "W": ("A + 关闭轮询 --poll 0", 24, ["-ngl", "40", "--cpu-moe", "--poll", "0"]),
    "X": ("A + 严格核绑定 --cpu-strict 1", 24,
          ["-ngl", "40", "--cpu-moe", "--cpu-strict", "1"]),
    "Y": ("纯 CPU 参考（-ngl 0）", 24, ["-ngl", "0"]),
    "AA": ("A + 绑 0-15（-t 16 -Cr 0-15）", 16,
           ["-ngl", "40", "--cpu-moe", "-Cr", "0-15"]),
    "AB": ("A + 绑单 CCD（-t 8 -Cr 0-7）", 8,
           ["-ngl", "40", "--cpu-moe", "-Cr", "0-7"]),
    "AC": ("A + 绑另一个 CCD（-t 8 -Cr 8-15）", 8,
           ["-ngl", "40", "--cpu-moe", "-Cr", "8-15"]),
    "AD": ("A 的层数换 38", 24, ["-ngl", "38", "--cpu-moe"]),
    "AE": ("A 的层数换 39", 24, ["-ngl", "39", "--cpu-moe"]),
    "AF": ("A + ngram-simple 投机（无需起草模型）", 24,
           ["-ngl", "40", "--cpu-moe", "--spec-type", "ngram-simple"]),
    "G1": ("去掉 mmproj（纯文本部署）", 24, ["-ngl", "40", "--cpu-moe"]),
    "G2": ("A 重跑（波动基线）", 24, ["-ngl", "40", "--cpu-moe"]),
}

ROUNDS = {"short": 2, "full": 1}   # full 口径只跑一轮：prefill 15K 太贵


# full 口径的目标提示长度（字符）。英文约 4 字符/token，
# 56000 字符 ≈ 14K token，加 ASK 后约 14.1K，给 256 生成留足余量。
FULL_TARGET_CHARS = 56000


def build_prompt(mode):
    if mode == "short":
        return ASK
    reps = max(1, FULL_TARGET_CHARS // max(1, len(FILL)))
    return FILL * reps + "\n\n" + ASK


def post(path, payload, timeout=1800):
    req = urllib.request.Request(
        BASE + path, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError("HTTP %d: %s" % (e.code, e.read()[:300].decode("utf-8", "replace")))


def wait_ready(proc, limit=420):
    t0 = time.time()
    while time.time() - t0 < limit:
        if proc.poll() is not None:
            return False
        try:
            with urllib.request.urlopen(BASE + "/health", timeout=3) as r:
                if r.status == 200 and b"ok" in r.read():
                    return True
        except Exception:
            pass
        time.sleep(1.5)
    return False


mode_cache = None


def measure(prompt, rounds, cache=False):
    global mode_cache
    mode_cache = cache if cache else None
    last = None
    for _ in range(rounds):
        r = post("/completion", {"prompt": prompt, "n_predict": 256,
                                 "temperature": 0.0, "top_k": 1,
                                 "cache_prompt": (mode_cache is not None)})
        t = r.get("timings", {})
        last = (t.get("predicted_per_second", 0.0), t.get("prompt_per_second", 0.0),
                t.get("prompt_n", 0), t.get("predicted_n", 0))
    return last


def run_one(name, mode):
    desc, threads, extra = PRESETS[name]
    common = COMMON
    if name in NO_MMPROJ:
        common = [x for i, x in enumerate(COMMON)
                  if x != "--mmproj" and (i == 0 or COMMON[i - 1] != "--mmproj")]
    args = [SERVER] + common + ["-t", str(threads)] + extra
    print("\n" + "-" * 78, flush=True)
    print("[%s/%s] %s" % (mode, name, desc), flush=True)
    logp = os.path.join(ROOT, "logs", "tune_%s_%s.log" % (mode, name))
    logf = open(logp, "wb")
    proc = subprocess.Popen(args, cwd=BIN, stdout=logf, stderr=subprocess.STDOUT)
    try:
        if not wait_ready(proc):
            logf.close()
            tail = open(logp, "rb").read()[-1200:].decode("utf-8", "replace")
            print("    [失败] 未就绪。日志尾部：\n%s" % tail, flush=True)
            return None
        rounds = int(os.environ.get("TUNE_ROUNDS", ROUNDS.get(mode, 1)))
        gen, pre, pn, gn = measure(build_prompt(mode), rounds, cache=(mode == "full"))
        print("    生成 %.2f t/s | prefill %.1f t/s | prompt %d tok | 生成 %d tok"
              % (gen, pre, pn, gn), flush=True)
        return (mode, name, desc, gen, pre, pn)
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=20)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        logf.close()
        time.sleep(3)


def main():
    argv = sys.argv[1:]
    modes = ["short"]
    if argv and argv[0] == "--mode":
        modes = argv[1].split(",")
        argv = argv[2:]
    want = argv or list(PRESETS.keys())

    out = []
    for mode in modes:
        for name in want:
            if name not in PRESETS:
                print("跳过未知组：%s" % name)
                continue
            r = run_one(name, mode)
            if r and r[3] > 0:
                out.append(r)

    for mode in modes:
        rows = [r for r in out if r[0] == mode]
        if not rows:
            continue
        print("\n" + "=" * 78)
        print("口径 %s 结果（按生成速度降序）" % mode)
        print("%-4s %-40s %8s %9s %8s" % ("组", "说明", "生成 t/s", "prefill", "prompt"))
        print("-" * 78)
        for _, name, desc, gen, pre, pn in sorted(rows, key=lambda x: -x[3]):
            print("%-4s %-40s %8.2f %9.1f %8d" % (name, desc[:40], gen, pre, pn))
    print("=" * 78)


if __name__ == "__main__":
    main()
