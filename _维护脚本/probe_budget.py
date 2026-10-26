# -*- coding: utf-8 -*-
"""显存预算对账探针 —— 验证「预算算的」与「实际用的」差多少

用法：
    python _维护脚本/probe_budget.py 1        # 32K 档
    python _维护脚本/probe_budget.py 3        # 64K 档
    python _维护脚本/probe_budget.py 1 5.0    # 第 2 参数=采样间隔秒（默认 0.35）

做的事：
  1) 记录启动前 baseline（桌面 + 驱动已占）
  2) 走真实 bat 启动，抓 bat 打印的 GPU_BUDGET / GPU_STRATEGY 原文
  3) 全程后台线程按固定间隔采样 nvidia-smi memory.used
  4) 分阶段记录峰值：加载后（静态）、prefill 中、decode 中、全程
  5) 给出「还剩多少可用」「按 40 MiB/层 还能多上几层」

输出只读，不改任何配置。
"""
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BAT = os.path.join(ROOT, "启动大模型_StartModel.bat")
LOGDIR = os.path.join(ROOT, "logs")
HOST, PORT = "127.0.0.1", 35035
TIER_DESC = {"1": "32K", "2": "48K", "3": "64K", "4": "96K",
             "5": "128K", "6": "160K", "7": "192K"}
LAYER_MIB = 40          # 非专家权重 / 层
TOTAL_MIB = 3072

for _k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
    os.environ.pop(_k, None)
os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"


def api_key():
    p = os.path.join(ROOT, "api-key.txt")
    if not os.path.exists(p):
        return ""
    with open(p, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            s = line.strip()
            if s and not s.startswith("#"):
                return s
    return ""


KEY = api_key()


def vram():
    try:
        o = subprocess.run(["nvidia-smi", "--query-gpu=memory.used",
                            "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=15)
        return int(o.stdout.strip().split("\n")[0])
    except Exception:
        return -1


def run_bat(*args, timeout=240):
    return subprocess.run(["cmd", "/c", BAT] + list(args) + ["quiet"],
                          capture_output=True, text=True, encoding="gbk",
                          errors="replace", cwd=ROOT, timeout=timeout)


def kill_server():
    subprocess.run(["taskkill", "/F", "/IM", "llama-server.exe"],
                   capture_output=True, text=True, encoding="gbk", errors="replace")


def newest_log():
    if not os.path.isdir(LOGDIR):
        return None
    logs = [os.path.join(LOGDIR, f) for f in os.listdir(LOGDIR)
            if f.startswith("server-") and f.endswith(".log")]
    return max(logs, key=os.path.getmtime) if logs else None


def read_log(p):
    try:
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception:
        return ""


def wait_ready(before, timeout=600):
    t0 = time.time()
    while time.time() - t0 < timeout:
        lp = newest_log()
        if lp and os.path.getmtime(lp) > before - 1:
            txt = read_log(lp)
            if "listening on" in txt or "server is listening" in txt:
                return True, lp, txt
        time.sleep(2)
    return False, newest_log(), read_log(newest_log() or "")


def post(path, payload, timeout=900):
    body = json.dumps(payload).encode("utf-8")
    hdr = {"Content-Type": "application/json"}
    if KEY:
        hdr["Authorization"] = "Bearer %s" % KEY
    req = urllib.request.Request("http://%s:%d%s" % (HOST, PORT, path),
                                 data=body, headers=hdr)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


class Sampler(threading.Thread):
    def __init__(self, interval):
        super().__init__(daemon=True)
        self.interval = interval
        self.samples = []           # (t, used)
        self.phase = "pre"
        self.stop = False

    def run(self):
        t0 = time.time()
        while not self.stop:
            u = vram()
            if u >= 0:
                self.samples.append((time.time() - t0, u, self.phase))
            time.sleep(self.interval)

    def peak(self, phase=None):
        xs = [u for _, u, p in self.samples if phase is None or p == phase]
        return max(xs) if xs else -1

    def tail(self, phase, k=8):
        xs = [u for _, u, p in self.samples if p == phase]
        return round(sum(xs[-k:]) / len(xs[-k:]), 1) if xs else -1


def main():
    tier = sys.argv[1] if len(sys.argv) > 1 else "1"
    interval = float(sys.argv[2]) if len(sys.argv) > 2 else 0.35
    desc = TIER_DESC.get(tier, "?")

    print("=" * 70)
    print("档位 %s — %s 上下文 · 采样间隔 %.2fs" % (tier, desc, interval))
    print("=" * 70, flush=True)

    kill_server()
    time.sleep(2)
    baseline = vram()
    print("启动前 baseline（桌面+驱动已占）：%d MiB，物理可用 %d MiB"
          % (baseline, TOTAL_MIB - baseline), flush=True)

    sp = Sampler(interval)
    sp.start()

    before = os.path.getmtime(newest_log()) if newest_log() else 0
    r = run_bat("start", tier, "nothink")
    out = (r.stdout or "")

    # 抓预算原文
    for pat, label in ((r"GPU 预算.*", "预算行"), (r"显存 3072 MiB -.*", "预算明细"),
                       (r"非专家权重上显存.*", "策略行")):
        m = re.search(pat, out)
        if m:
            print("\n--- %s ---\n%s" % (label, m.group(0).strip()))

    ok, lp, txt = wait_ready(before)
    if not ok:
        sp.stop = True
        print("[FAIL] 未就绪")
        print(txt[-1200:])
        return 2

    print("[OK] 已监听 %s" % lp, flush=True)
    m = re.search(r"n_gpu_layers already set by user to (\d+)", txt)
    ngl = int(m.group(1)) if m else -1
    mctx = re.search(r"n_ctx_slot\s*=\s*(\d+)", txt)
    nctx = int(mctx.group(1)) if mctx else -1
    print("  -ngl=%d  n_ctx=%d" % (ngl, nctx), flush=True)

    time.sleep(1.5)
    sp.phase = "load"
    load_used = vram()
    print("  加载后静态占用：%d MiB（llama 本体 %d MiB）"
          % (load_used, load_used - baseline), flush=True)

    # 短对话
    try:
        post("/v1/chat/completions", {"model": "local",
             "messages": [{"role": "user", "content": "说一句话。"}],
             "max_tokens": 16, "temperature": 0.0}, timeout=300)
    except Exception as e:
        print("[WARN] 短对话失败 %r" % (e,))

    # prefill
    filler = ("深度学习模型在推理阶段的主要瓶颈是内存带宽而不是浮点算力。"
              "混合专家架构每个 token 只激活少数专家，因此权重必须常驻内存。")
    sp.phase = "prefill"
    try:
        d = post("/completion", {"prompt": filler * 375, "n_predict": 1,
                                 "temperature": 0.0, "cache_prompt": False})
        t = d.get("timings") or {}
        pp_n, pp_tps = t.get("prompt_n"), t.get("prompt_per_second")
        print("[OK] prefill %s token → %.1f t/s" % (pp_n, pp_tps or 0), flush=True)
    except Exception as e:
        pp_n, pp_tps = None, None
        print("[FAIL] prefill %r" % (e,))

    # decode
    sp.phase = "decode"
    try:
        d = post("/completion", {"prompt": "请用大约一百字介绍 MoE 的工作原理。",
                                 "n_predict": 128, "temperature": 0.0,
                                 "cache_prompt": False})
        t = d.get("timings") or {}
        tg_tps, tg_n = t.get("predicted_per_second"), t.get("predicted_n")
        print("[OK] decode %s token → %.2f t/s" % (tg_n, tg_tps or 0), flush=True)
    except Exception as e:
        tg_tps, tg_n = None, None
        print("[FAIL] decode %r" % (e,))

    time.sleep(1.0)
    sp.stop = True
    sp.join(timeout=5)

    pk_all = sp.peak()
    pk_load = sp.peak("load")
    pk_pp = sp.peak("prefill")
    pk_tg = sp.peak("decode")

    print("\n" + "-" * 70)
    print("显存实测（%d MiB 卡，baseline %d MiB）" % (TOTAL_MIB, baseline))
    print("-" * 70)
    print("  加载后        : %5d MiB（llama %d）" % (pk_load, pk_load - baseline))
    print("  prefill 峰值  : %5d MiB（llama %d）" % (pk_pp, pk_pp - baseline))
    print("  decode  峰值  : %5d MiB（llama %d）" % (pk_tg, pk_tg - baseline))
    print("  全程峰值      : %5d MiB（llama %d）" % (pk_all, pk_all - baseline))
    head = TOTAL_MIB - pk_all
    print("  距满卡余量    : %5d MiB → 按 %d MiB/层 ≈ 还能多上 %d 层"
          % (head, LAYER_MIB, head // LAYER_MIB))
    print("\n  小结：-ngl=%d  ctx=%d  prefill=%s t/s  decode=%s t/s"
          % (ngl, nctx, pp_tps, tg_tps))

    print("\n== 关闭 ==", flush=True)
    run_bat("stop")
    kill_server()
    return 0


if __name__ == "__main__":
    sys.exit(main())
