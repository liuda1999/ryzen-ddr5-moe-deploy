# -*- coding: utf-8 -*-
"""3 GB 标定卡 · 32K / 64K 档位跑通验收

用法：
    python _维护脚本/verify_3g.py          # 默认测档位 1（32K）和 3（64K）
    python _维护脚本/verify_3g.py 1 3 4    # 指定档位

每档都走真实链路（启动大模型_StartModel.bat start <档位>），依次做：
  1) 清残留进程 → 启动 → 等 "server is listening"
  2) 从日志校验：线程数、n_ctx、GPU 层数、专家层、KV 精度、显存缓冲
  3) /v1/chat/completions 短对话 —— 验证能正常返回
  4) /completion 长提示（约 4K token）—— 验证 prefill 不报错并测速
  5) /completion 短提示 + 128 token 生成 —— 测 decode 速度，期间采样显存
  6) bat stop 关闭

判据：无 traceback / 无 CUDA OOM / 能出 token / 线程数为 16。
"""
import json
import os
import re
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BAT = os.path.join(ROOT, "启动大模型_StartModel.bat")
LOGDIR = os.path.join(ROOT, "logs")
HOST = "127.0.0.1"
PORT = 35035

# 沙箱代理会拦 127.0.0.1，必须清掉
for _k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
    os.environ.pop(_k, None)
os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"

TIER_DESC = {"1": "32K", "2": "48K", "3": "64K", "4": "96K",
             "5": "128K", "6": "160K", "7": "192K"}


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


def run_bat(*args, timeout=180):
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
    if not logs:
        return None
    return max(logs, key=os.path.getmtime)


def read_log(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception:
        return ""


def wait_ready(before_mtime, timeout=600):
    """等新日志出现 listening。返回 (ok, logpath, text)。"""
    t0 = time.time()
    while time.time() - t0 < timeout:
        lp = newest_log()
        if lp and os.path.getmtime(lp) > before_mtime - 1:
            txt = read_log(lp)
            if "server is listening" in txt or "listening on" in txt:
                return True, lp, txt
            if "error" in txt.lower() and "failed to" in txt.lower():
                return False, lp, txt
        time.sleep(5)
    return False, newest_log(), read_log(newest_log() or "")


def vram():
    try:
        o = subprocess.run(["nvidia-smi", "--query-gpu=memory.used",
                            "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=15)
        return int(o.stdout.strip().split("\n")[0])
    except Exception:
        return -1


def post(path, payload, timeout=300):
    body = json.dumps(payload).encode("utf-8")
    hdr = {"Content-Type": "application/json"}
    if KEY:
        hdr["Authorization"] = "Bearer %s" % KEY
    req = urllib.request.Request("http://%s:%d%s" % (HOST, PORT, path),
                                 data=body, headers=hdr)
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read().decode("utf-8"))
    return data, time.time() - t0


def parse_facts(txt):
    """从 server 日志里抠关键事实（对齐 llama-server 的 verbosity=3 输出格式）。"""
    facts = {}
    m = re.search(r"threadpool init,\s*n_threads\s*=\s*(\d+)", txt)
    if m:
        facts["threads"] = int(m.group(1))
    m = re.search(r"n_ctx_slot\s*=\s*(\d+)", txt) or re.search(r"n_ctx\s*=\s*(\d+)", txt)
    if m:
        facts["n_ctx"] = int(m.group(1))
    m = re.search(r"n_slots\s*=\s*(\d+)", txt)
    if m:
        facts["n_slots"] = int(m.group(1))
    m = re.search(r"kv_unified\s*=\s*'(\w+)'", txt)
    if m:
        facts["kv_unified"] = m.group(1)
    m = re.search(r"n_gpu_layers already set by user to (\d+)", txt)
    if m:
        facts["gpu_layers"] = int(m.group(1))
    m = re.search(r"failed to fit params to free device memory", txt)
    if m:
        facts["fit_warning"] = True
    return facts


def run_tier(tier):
    desc = TIER_DESC.get(tier, "?")
    print("\n" + "=" * 72)
    print("档位 %s —— %s 上下文" % (tier, desc))
    print("=" * 72, flush=True)

    kill_server()
    time.sleep(2)

    try:
        o = subprocess.run(["nvidia-smi", "--query-gpu=memory.free",
                            "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=15)
        free_mib = int(o.stdout.strip().split("\n")[0])
    except Exception:
        free_mib = -1

    before = os.path.getmtime(newest_log()) if newest_log() else 0
    r = run_bat("start", tier, "nothink")
    out = (r.stdout or "").strip()
    if out:
        print("--- bat 输出（截断）---")
        print("\n".join(out.split("\n")[:28]))
        print("-----------------------", flush=True)

    ok, lp, txt = wait_ready(before)
    if not ok:
        print("[FAIL] 未就绪，日志尾部：")
        print(txt[-1500:])
        return {"tier": tier, "ctx": desc, "ok": False, "reason": "未进入监听"}

    print("[OK] 服务已监听：%s" % lp, flush=True)
    facts = parse_facts(txt)
    # KV 精度与显存策略从 bat 启动输出里读（server 日志 verbosity=3 不打印这些）
    mkv = re.search(r"--cache-type-k\s+(\w+)", out)
    if mkv:
        facts["kv"] = mkv.group(1)
    mstrat = re.search(r"专家上显存\s*(\d+)\s*层", out)
    if mstrat:
        facts["expert_gpu"] = int(mstrat.group(1))
    print("--- 运行参数 ---")
    print("  线程 threads     : %s" % facts.get("threads"))
    print("  上下文 n_ctx     : %s" % facts.get("n_ctx"))
    print("  并发槽 n_slots   : %s（kv_unified=%s）"
          % (facts.get("n_slots"), facts.get("kv_unified")))
    print("  GPU 层数 -ngl    : %s" % facts.get("gpu_layers"))
    print("  KV 精度          : %s" % facts.get("kv"))
    print("  启动前空闲显存   : %s MiB" % free_mib)
    if facts.get("fit_warning"):
        print("  提示             : 显存不足，--fit 放弃自动调层（沿用预算算出的层数）")
    print(flush=True)

    result = {"tier": tier, "ctx": desc, "ok": True, "facts": facts}

    # T1 短对话
    try:
        t0 = time.time()
        d, el = post("/v1/chat/completions", {
            "model": "local",
            "messages": [{"role": "user", "content": "用一句话说明你是什么模型。"}],
            "max_tokens": 32, "temperature": 0.0,
        }, timeout=180)
        msg = d["choices"][0]["message"]["content"].strip()
        result["chat"] = msg[:120]
        print("[OK] 短对话 %.1fs：%s" % (el, msg[:80]), flush=True)
    except Exception as e:
        print("[FAIL] 短对话：%r" % (e,))
        result["ok"] = False
        result["reason"] = "chat 失败: %r" % (e,)
        return result

    # T2 长提示 prefill（约 12K token，占 32K 档的 37%、64K 档的 19%）
    filler = ("深度学习模型在推理阶段的主要瓶颈是内存带宽而不是浮点算力。"
              "混合专家架构每个 token 只激活少数专家，因此权重必须常驻内存。")
    long_prompt = filler * 375
    try:
        d, el = post("/completion", {
            "prompt": long_prompt, "n_predict": 1,
            "temperature": 0.0, "cache_prompt": False,
        }, timeout=600)
        t = d.get("timings") or {}
        pp_n, pp_tps = t.get("prompt_n"), t.get("prompt_per_second")
        result["pp_n"], result["pp_tps"] = pp_n, pp_tps
        print("[OK] 长提示 prefill：%s token / %.2f s → %.1f t/s"
              % (pp_n, t.get("prompt_ms", 0) / 1000.0, pp_tps or 0), flush=True)
    except Exception as e:
        print("[FAIL] prefill：%r" % (e,))
        result["ok"] = False
        result["reason"] = "prefill 失败: %r" % (e,)
        return result

    # T3 decode + 显存采样
    peak = [0]

    try:
        d, el = post("/completion", {
            "prompt": "请用大约一百字介绍混合专家模型（MoE）的工作原理。",
            "n_predict": 128, "temperature": 0.0, "cache_prompt": False,
        }, timeout=600)
        used = vram()
        peak[0] = used
        t = d.get("timings") or {}
        tg_tps = t.get("predicted_per_second")
        result["tg_tps"] = tg_tps
        result["tg_n"] = t.get("predicted_n")
        result["vram_used"] = used
        print("[OK] decode：%s token → %.2f t/s，显存 %s / 3072 MiB"
              % (t.get("predicted_n"), tg_tps or 0, used), flush=True)
        preview = (d.get("content") or "").replace("\n", " ")[:100]
        print("     输出预览：%s" % preview, flush=True)
    except Exception as e:
        print("[FAIL] decode：%r" % (e,))
        result["ok"] = False
        result["reason"] = "decode 失败: %r" % (e,)
        return result

    # 判据
    issues = []
    if facts.get("threads") != 16:
        issues.append("线程数为 %s，预期 16" % facts.get("threads"))
    expect_ctx = {"1": 32768, "3": 65536}.get(tier)
    if expect_ctx and facts.get("n_ctx") != expect_ctx:
        issues.append("n_ctx=%s，预期 %s" % (facts.get("n_ctx"), expect_ctx))
    if used < 0 or used > 3072:
        issues.append("显存读数异常 %s" % used)
    result["issues"] = issues
    if issues:
        result["ok"] = False
        print("[WARN] " + "；".join(issues), flush=True)
    return result


def main():
    tiers = sys.argv[1:] or ["1", "3"]
    free_before = 0
    try:
        o = subprocess.run(["nvidia-smi", "--query-gpu=memory.free",
                            "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=15)
        free_before = int(o.stdout.strip().split("\n")[0])
    except Exception:
        pass
    print("启动前空闲显存：%s MiB" % free_before)

    results = []
    for t in tiers:
        try:
            res = run_tier(t)
        except Exception as e:
            res = {"tier": t, "ctx": TIER_DESC.get(t, "?"), "ok": False,
                   "reason": "异常: %r" % (e,)}
            print("[FAIL] 档位 %s 异常：%r" % (t, e))
        results.append(res)
        print("\n== 关闭档位 %s ==" % t, flush=True)
        run_bat("stop")
        kill_server()
        time.sleep(4)

    print("\n" + "=" * 72)
    print("汇总")
    print("=" * 72)
    all_ok = True
    for r in results:
        f = r.get("facts") or {}
        status = "PASS" if r.get("ok") else "FAIL"
        if not r.get("ok"):
            all_ok = False
        print("[%s] 档位 %s（%s）线程=%s n_ctx=%s -ngl=%s KV=%s"
              % (status, r["tier"], r["ctx"], f.get("threads"),
                 f.get("n_ctx"), f.get("gpu_layers"), f.get("kv")))
        if r.get("pp_tps"):
            print("        prefill %s token → %.1f t/s" % (r.get("pp_n"), r["pp_tps"]))
        if r.get("tg_tps"):
            print("        decode  %s token → %.2f t/s，显存 %s MiB"
                  % (r.get("tg_n"), r["tg_tps"], r.get("vram_used")))
        if r.get("chat"):
            print("        短对话：%s" % r["chat"])
        if r.get("reason"):
            print("        原因：%s" % r["reason"])
        if r.get("issues"):
            print("        问题：%s" % "；".join(r["issues"]))
    print("\n结论：%s" % ("全部通过" if all_ok else "存在失败项"))
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
