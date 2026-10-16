# -*- coding: utf-8 -*-
"""聚焦实验：隔离「上下文大小」对 GPU 卸载收益的影响。

背景：llama-bench 在默认小上下文下测到 +48%（15.09 -> 22.40 t/s），
但 16K 上下文的真实服务端没有收益。怀疑变量是 VRAM 压力
（权重要 2.0+ GiB，3 GB 卡只剩 2.4 GiB，加上 KV / 计算缓冲后
在 WDDM 下会被驱动分页到系统内存，PCIe 往返把收益吃光）。

设计：固定提示长度与生成长度，只改 -c 与卸载参数，两两对比。
输出：E:/llm-cpp-gpu-test/ctx_matrix.csv（控制台仅 ASCII）
"""
import io, json, os, re, subprocess, time, urllib.request

BIN = r"E:\llm-cpp\llama.cpp\build-zen5\bin"
MODEL = r"E:\llm-cpp\llama.cpp\models\Qwen3.6-35B-A3B-UD-Q4_K_M.gguf"
OUT = r"E:\llm-cpp-gpu-test\ctx_matrix.csv"
PORT = 35079
PROMPT = "Summarize briefly: " + ("the quick brown fox jumps over the lazy dog. " * 6)
MAXTOK = 128

# (tag, ctx, extra args)
# 假设：3 GB 卡的可用显存约 2.6 GiB，一旦总需求越过它，WDDM 就把显存分页到
# 系统内存，PCIe 往返把收益吃光（16K 下实测 14.6 -> 6.1 t/s）。
# 所以按「留出多少余量」扫描，找出既上显存又不越界的工作点。
CONFIGS = [
    ("c16k-cpu",         16384, ["--n-gpu-layers", "0"]),
    ("c16k-ngl41",       16384, ["--n-gpu-layers", "41", "--cpu-moe"]),
    ("c16k-ngl41-p1",    16384, ["--parallel", "1", "--n-gpu-layers", "41", "--cpu-moe"]),
    ("c16k-ngl41-ncmoe", 16384, ["--n-gpu-layers", "41", "--n-cpu-moe", "99"]),
    ("c16k-ngl41-nkvo",  16384, ["--n-gpu-layers", "41", "--cpu-moe", "-nkvo"]),
]


def vram():
    try:
        o = subprocess.run([r"C:\Windows\System32\nvidia-smi.exe",
                            "--query-gpu=memory.used,memory.total",
                            "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=15)
        u, t = o.stdout.strip().split("\n")[0].split(",")
        return int(u), int(t)
    except Exception:
        return (0, 0)


def health():
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/health" % PORT, timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def chat():
    body = json.dumps({"messages": [{"role": "user", "content": PROMPT}],
                       "max_tokens": MAXTOK, "stream": False}).encode()
    req = urllib.request.Request("http://127.0.0.1:%d/v1/chat/completions" % PORT,
                                 data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=900) as r:
        return json.loads(r.read().decode("utf-8"))


def run_one(tag, ctx, extra):
    log = os.path.join(r"E:\llm-cpp-gpu-test", "ctx_%s.log" % tag)
    args = ([os.path.join(BIN, "llama-server.exe"), "--model", MODEL,
             "--host", "127.0.0.1", "--port", str(PORT),
             "--ctx-size", str(ctx), "--threads", "24", "--threads-batch", "24",
             "--reasoning", "off"] + extra)
    with open(log, "wb") as lf:
        p = subprocess.Popen(args, stdout=lf, stderr=subprocess.STDOUT,
                             cwd=BIN, stdin=subprocess.DEVNULL)
        t0 = time.time()
        while time.time() - t0 < 300:
            if p.poll() is not None:
                txt = io.open(log, "rb").read().decode("utf-8", "replace")
                return dict(tag=tag, note="START_FAILED: " + txt[-300:].replace("\n", " "))
            if health():
                break
            time.sleep(2)
        else:
            p.kill(); p.wait(timeout=30)
            return dict(tag=tag, note="TIMEOUT_WAIT_READY")

        ready = time.time() - t0
        vu, vt = vram()
        txt = io.open(log, "rb").read().decode("utf-8", "replace")
        offl = ""
        m = re.search(r"offloaded (\d+/\d+ layers to GPU)", txt)
        if m:
            offl = m.group(1)
        # 第一次（冷）与第二次（缓存热）各一次
        d1 = chat(); d2 = chat()
        t1, t2 = d1["timings"], d2["timings"]
        p.terminate()
        try:
            p.wait(timeout=60)
        except subprocess.TimeoutExpired:
            p.kill(); p.wait(timeout=30)
        return dict(tag=tag, note="OK", ctx=ctx, offl=offl,
                    vram_used=vu, vram_total=vt,
                    ready_s=round(ready, 1),
                    pp_n=t1.get("prompt_n", 0),
                    pp_tps=round(t1.get("prompt_per_second", 0), 1),
                    tg_tps=round(t1.get("predicted_per_second", 0), 2),
                    tg_tps2=round(t2.get("predicted_per_second", 0), 2),
                    tg_n1=t1.get("predicted_n", 0), tg_n2=t2.get("predicted_n", 0))


def main():
    rows = []
    for tag, ctx, extra in CONFIGS:
        print("=" * 64)
        print("  [%s] ctx=%d  %s" % (tag, ctx, " ".join(extra)))
        print("=" * 64)
        r = run_one(tag, ctx, extra)
        rows.append(r)
        print("  " + json.dumps(r, ensure_ascii=True))
        time.sleep(3)
    keys = ["tag", "ctx", "note", "offl", "vram_used", "vram_total",
            "ready_s", "pp_n", "pp_tps", "tg_tps", "tg_tps2", "tg_n1", "tg_n2"]
    with io.open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write(",".join(keys) + "\n")
        for r in rows:
            f.write(",".join(str(r.get(k, "")) for k in keys) + "\n")
    print()
    print("%-18s %6s %-18s %9s %8s %8s %8s" % ("config", "ctx", "offload", "vram", "pp_tps", "tg_cold", "tg_warm"))
    for r in rows:
        print("%-18s %6s %-18s %9s %8s %8s %8s" % (
            r.get("tag", ""), r.get("ctx", ""), r.get("offl", r.get("note", ""))[:18],
            "%s/%s" % (r.get("vram_used", ""), r.get("vram_total", "")),
            r.get("pp_tps", ""), r.get("tg_tps", ""), r.get("tg_tps2", "")))
    print()
    print("saved: " + OUT)


if __name__ == "__main__":
    main()
