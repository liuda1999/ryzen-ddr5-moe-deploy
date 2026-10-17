# -*- coding: utf-8 -*-
"""多档位 × 多轮 真实运行审计（发版前回归用）

对指定档位各跑 N 轮：走项目启动脚本真实拉起服务 -> 深上下文预填充 -> 生成长回答，
全程采样 CPU / GPU / 显存，并汇总每轮的速度与上下文，用于确认「改动后各档位仍可用」。

用法：
    python audit_tiers.py                 # 默认档位 1 3 4，各跑 2 轮
    python audit_tiers.py --tiers 1 3 4 --rounds 2
    python audit_tiers.py --tiers 4 --rounds 1 --targets 4:30000

注意：会真实占用整机算力数分钟；跑完自动关闭服务。
"""
import argparse
import glob
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BAT = os.path.join(ROOT, "启动大模型_StartModel.bat")
PORT = 35035
HOST = "http://127.0.0.1:%d" % PORT

for _k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
           "ALL_PROXY", "all_proxy"):
    os.environ.pop(_k, None)
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

# 各档位预填充目标 token 数（档位号 -> token）
DEFAULT_TARGET = {1: 6000, 3: 16000, 4: 30000}

PARA = ("第{i}节 本地推理工程记录：显存与内存混合承担是让消费级显卡跑动大型混合专家模型的关键手段，"
        "非专家权重常驻显存、占大头的专家权重留在内存，每个 token 只从内存读取被激活的少数专家。"
        "这样既降低了显存门槛，又把每 token 必读的权重放到了带宽更高的显存里。")


def api_key():
    p = os.path.join(ROOT, "api-key.txt")
    if not os.path.exists(p):
        return ""
    for line in open(p, encoding="utf-8", errors="replace"):
        line = line.strip()
        if line and not line.startswith("#"):
            return line
    return ""


KEY = api_key()
HEADERS = {"Content-Type": "application/json"}
if KEY:
    HEADERS["Authorization"] = "Bearer %s" % KEY


def post(path, payload, timeout=3600):
    req = urllib.request.Request(
        HOST + path, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=HEADERS)
    with OPENER.open(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def ntok(text):
    return len(post("/tokenize", {"content": text})["tokens"])


def wait_ready(limit=600):
    t0 = time.time()
    while time.time() - t0 < limit:
        try:
            with OPENER.open(HOST + "/health", timeout=5) as r:
                if r.status == 200:
                    return time.time() - t0
        except Exception:
            time.sleep(3)
    return None


def run_bat(*args, timeout=900):
    return subprocess.run(["cmd", "/c", BAT] + list(args), capture_output=True,
                          text=True, encoding="gbk", errors="replace",
                          cwd=ROOT, timeout=timeout)


def kill_server():
    subprocess.run(["taskkill", "/F", "/IM", "llama-server.exe"],
                   capture_output=True)


def sample_once():
    """返回 (cpu%, gpu%, vram_MiB)"""
    cmd = ("$c=$null;"
           "try{$c=(Get-Counter '\\Processor(_Total)\\% Processor Time' -MaxSamples 1)"
           ".CounterSamples[0].CookedValue}catch{};"
           "if($null -eq $c){$c=(Get-CimInstance Win32_Processor).LoadPercentage};"
           "$g=(nvidia-smi --query-gpu=utilization.gpu,memory.used "
           "--format=csv,noheader,nounits);"
           "Write-Output \"$c|$g\"")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", cmd],
                             capture_output=True, text=True, timeout=25)
        line = out.stdout.strip().splitlines()[-1]
        parts = [x.strip() for x in line.split("|")]
        cpu = float(parts[0])
        g = parts[1].split(",")
        return cpu, float(g[0]), float(g[1])
    except Exception:
        return None


class Sampler(threading.Thread):
    def __init__(self, t0):
        super().__init__(daemon=True)
        self.stop_flag = False
        self.rows = []
        self.t0 = t0

    def run(self):
        while not self.stop_flag:
            s = sample_once()
            if s:
                self.rows.append((time.time() - self.t0,) + s)
            time.sleep(3)

    def stop(self):
        self.stop_flag = True

    def phase(self, a, b):
        """按时间区间 [a,b] 汇总"""
        v = [r for r in self.rows if a <= r[0] <= b]
        if not v:
            return "无样本"
        cpu = [r[1] for r in v]
        gpu = [r[2] for r in v]
        mem = [r[3] for r in v]
        return ("%d样本 CPU %.0f%%(%.0f~%.0f) GPU %.0f%%(%.0f~%.0f) 显存 %.0f~%.0fMiB"
                % (len(v), sum(cpu) / len(cpu), min(cpu), max(cpu),
                   sum(gpu) / len(gpu), min(gpu), max(gpu), min(mem), max(mem)))


def build_doc(target, unit):
    need = max(1, int(target / unit))
    return "".join(PARA.format(i=i) for i in range(1, need + 1))


def newest_log():
    logs = glob.glob(os.path.join(ROOT, "logs", "server-*.log"))
    return max(logs, key=os.path.getmtime) if logs else None


def one_round(tier, rnd, target):
    kill_server()
    time.sleep(2)
    res = {"tier": tier, "round": rnd, "target": target}
    t_start = time.time()
    try:
        r = run_bat("start", str(tier), "nothink", "quiet")
        out = r.stdout or ""
        res["startup_line"] = next(
            (l.strip() for l in out.splitlines() if "GPU 参数" in l), "")
        ready = wait_ready()
        if ready is None:
            res["error"] = "服务未就绪"
            return res
        res["load_s"] = round(time.time() - t_start, 1)

        log = newest_log()
        res["log"] = os.path.basename(log) if log else ""
        if log:
            txt = open(log, encoding="utf-8", errors="replace").read()
            for line in txt.splitlines():
                if "n_ctx_slot" in line:
                    m = re.search(r"n_ctx_slot\s*=\s*(\d+)", line)
                    if m:
                        res["n_ctx_slot"] = m.group(1)
                if "offloaded" in line and "layers" in line:
                    res["offload"] = line.strip()[-100:]

        # 用真实服务分词校准，再按目标 token 数造文档
        unit = max(1, ntok(PARA.format(i=1)))
        doc = build_doc(target, unit)
        res["prompt_tokens"] = ntok(doc)

        t0 = time.time()
        sm = Sampler(t0)
        sm.start()
        t_a = time.time() - t0

        # 1) 短对话（浅上下文 decode 基线）
        r1 = post("/v1/chat/completions", {
            "messages": [{"role": "user", "content": "用一句话说明什么是混合专家模型。"}],
            "max_tokens": 48, "temperature": 0.0,
            "chat_template_kwargs": {"enable_thinking": False}})
        t1 = r1.get("timings") or {}
        res["short_decode"] = round(t1.get("predicted_per_second", 0), 2)

        # 2) 深上下文：预填充 + 长生成
        t_b = time.time() - t0
        r2 = post("/v1/chat/completions", {
            "messages": [{"role": "user",
                          "content": doc + "\n\n请用三句话概括上面的内容。"}],
            "max_tokens": 256, "temperature": 0.0,
            "chat_template_kwargs": {"enable_thinking": False}})
        t2 = r2.get("timings") or {}
        t_c = time.time() - t0

        res["prefill_tps"] = round(t2.get("prompt_per_second", 0), 2)
        res["prefill_n"] = t2.get("prompt_n")
        res["decode_tps"] = round(t2.get("predicted_per_second", 0), 2)
        res["gen_n"] = t2.get("predicted_n")
        res["finish"] = r2["choices"][0].get("finish_reason")
        res["answer_len"] = len((r2["choices"][0]["message"].get("content") or "").strip())
        res["prefill_phase"] = sm.phase(t_b, t_b + t2.get("prompt_ms", 0) / 1000.0)
        res["decode_phase"] = sm.phase(t_b + t2.get("prompt_ms", 0) / 1000.0, t_c)
        res["short_phase"] = sm.phase(t_a, t_b)
        res["wall_s"] = round(time.time() - t_start, 1)
        sm.stop()
    except Exception as e:
        res["error"] = repr(e)
    finally:
        try:
            run_bat("stop", "quiet", timeout=180)
        except Exception:
            pass
        kill_server()
        time.sleep(2)
    return res




def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tiers", nargs="+", type=int, default=[1, 3, 4])
    ap.add_argument("--rounds", type=int, default=2)
    ap.add_argument("--targets", nargs="*", default=[],
                    help="如 4:30000 覆盖某档位的预填充目标")
    a = ap.parse_args()

    targets = dict(DEFAULT_TARGET)
    for item in a.targets:
        k, v = item.split(":")
        targets[int(k)] = int(v)

    kill_server()
    time.sleep(1)

    print("=" * 100)
    print("多档位真实运行审计：档位 %s，每档 %d 轮" % (a.tiers, a.rounds))
    print("目标预填充 token：%s" % {t: targets.get(t) for t in a.tiers})
    print("=" * 100, flush=True)

    allres = []
    for tier in a.tiers:
        for rnd in range(1, a.rounds + 1):
            print("\n---- 档位 %d / 第 %d 轮 ----" % (tier, rnd), flush=True)
            r = one_round(tier, rnd, targets.get(tier, 8000))
            allres.append(r)
            if "error" in r:
                print("  !! %s" % r["error"], flush=True)
                continue
            print("  载入 %.0fs | ctx %s | %s" % (r["load_s"], r.get("n_ctx_slot", "?"),
                                                r.get("startup_line", "")[:120]), flush=True)
            print("  短对话 decode  %.2f t/s" % r["short_decode"], flush=True)
            print("  预填充 %s tok  %.2f t/s | 生成 %s tok  %.2f t/s | finish=%s 正文%d字"
                  % (r["prefill_n"], r["prefill_tps"], r["gen_n"], r["decode_tps"],
                     r["finish"], r["answer_len"]), flush=True)
            print("  prefill 段 %s" % r["prefill_phase"], flush=True)
            print("  decode  段 %s" % r["decode_phase"], flush=True)

    print("\n" + "=" * 100)
    print("%-5s %-4s %-8s %-9s %-9s %-9s %-8s %-8s" % (
        "档", "轮", "ctx", "预填充tok", "prefill", "decode", "短对话", "状态"))
    print("-" * 100)
    for r in allres:
        if "error" in r:
            print("%-5d %-4d %-8s %-9s %-9s %-9s %-8s %-8s"
                  % (r["tier"], r["round"], "-", "-", "-", "-", "-", "失败:" + r["error"][:20]))
            continue
        print("%-5d %-4d %-8s %-9s %-9s %-9s %-8s %-8s"
              % (r["tier"], r["round"], r.get("n_ctx_slot", "?"), r["prefill_n"],
                 "%.1f t/s" % r["prefill_tps"], "%.2f t/s" % r["decode_tps"],
                 "%.1f t/s" % r["short_decode"], "OK"))
    print("=" * 100)

    bad = [r for r in allres if "error" in r]
    print("失败轮次：%d / %d" % (len(bad), len(allres)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
