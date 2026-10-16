# -*- coding: utf-8 -*-
"""64K 上下文 KV 量化对比台架：Q8(q8_0) vs F16，同机同模型，深上下文实测。

背景：脚本在 3 GB 卡上跑 64K 时会自动把 KV 降到 q8_0（f16 装不下足够层数）。
本台架回答两个问题：
  1. 64K + q8_0 KV 真实的 prefill / decode 是多少 t/s（深上下文填满 + 长回答）
  2. 如果坚持用 f16 KV（必须在 3 GB 卡上削减 GPU 层数），速度差多少
同时采样 decode 阶段的 CPU / GPU 利用率，确认资源是否跑满。

用法：
    python bench_kv64k.py                # 跑两组（Q8 + F16）
    python bench_kv64k.py --only q8      # 只跑 Q8
    python bench_kv64k.py --target 62000 --out 800
"""
import argparse
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BIN = os.path.join(ROOT, "llama.cpp", "build-zen5", "bin", "llama-server.exe")
MODEL = os.path.join(ROOT, "llama.cpp", "models", "Qwen3.6-35B-A3B-UD-Q4_K_M.gguf")
LOGDIR = os.path.join(ROOT, "logs")
PORT = 35035
HOST = "http://127.0.0.1:%d" % PORT
CTX = 65536
THREADS = 24

LONG_Q = (
    "\n\n请认真读完上面这份工程文档，然后写一份不少于 600 字的总结。"
    "要求分点，依次讲清楚：量化带来的收益与代价、MoE 为什么适合 CPU 推理、"
    "线程数该怎么选、内存带宽为什么是瓶颈、显存混合卸载解决的是什么问题。"
    "不要复述原文，用你自己的话概括。"
)
SHORT_Q = "用中文写一段 300 字左右的短文，谈谈本地部署大模型的价值。"

# 绕过沙箱代理，直连 127.0.0.1
for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
    os.environ.pop(k, None)
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def post(path, payload, timeout=7200):
    req = urllib.request.Request(
        HOST + path,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with _opener.open(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def tokenize(text):
    return len(post("/tokenize", {"content": text})["tokens"])


PARA = (
    "第{i}节 本地推理工程记录：在纯中央处理器环境下部署大语言模型，"
    "需要同时权衡模型体积、量化精度与内存带宽三者之间的关系。"
    "量化把权重从十六位浮点压缩到四位整数，显著降低了内存占用和带宽压力，"
    "但也会带来一定的精度损失。多专家混合架构在推理时只激活少量专家，"
    "因此实际计算量远小于参数总量所暗示的规模，这让中央处理器推理变得可行。"
    "线程调度方面，物理核心的利用率比逻辑线程数更值得关注，"
    "因为同步开销与内存带宽争用会在高并发时抵消并行收益。"
)


def build_doc(target_tokens):
    unit = tokenize(PARA.format(i=1))
    need = max(1, int(target_tokens / unit))
    return "".join(PARA.format(i=i) for i in range(1, need + 1)), need


class Sampler(threading.Thread):
    """后台采样 CPU / GPU 利用率，并按服务日志判断当前处于 prefill 还是 decode。

    为什么必须分阶段：prefill 是 GPU 瓶颈（CPU 只有几个百分点），decode 才是
    CPU 瓶颈。混在一起看会误判成「CPU 没干活」，所以采样时同步记录阶段。
    """

    def __init__(self, logpath):
        super().__init__(daemon=True)
        self.stop = False
        self.logpath = logpath
        self.rows = []          # (t, stage, cpu, gpu)

    def stage(self):
        """读服务日志尾部，判断当前是 prefill 还是 decode。"""
        try:
            with open(self.logpath, "rb") as f:
                f.seek(0, 2)
                size = f.tell()
                f.seek(max(0, size - 4000))
                tail = f.read().decode("utf-8", "replace")
            ip = tail.rfind("prompt processing")
            ig = tail.rfind("n_gen =")
            if ip < 0 and ig < 0:
                return "?"
            return "prefill" if ip > ig else "decode"
        except Exception:
            return "?"

    def run(self):
        t0 = time.time()
        while not self.stop:
            try:
                cmd = (
                    "$c = $null;"
                    "try { $c = (Get-Counter '\\Processor(_Total)\\% Processor Time' "
                    "-MaxSamples 1).CounterSamples[0].CookedValue } catch {};"
                    "if ($null -eq $c) { $c = (Get-CimInstance Win32_Processor).LoadPercentage };"
                    "$g = (nvidia-smi --query-gpu=utilization.gpu "
                    "--format=csv,noheader,nounits);"
                    "Write-Output \"$c|$g\"")
                out = subprocess.run(
                    ["powershell", "-NoProfile", "-Command", cmd],
                    capture_output=True, text=True, timeout=25)
                line = out.stdout.strip().splitlines()[-1]
                c, g = line.split("|")
                self.rows.append((time.time() - t0, self.stage(), float(c), float(g.strip())))
            except Exception:
                pass
            time.sleep(4)

    def report(self):
        def stat(rows, tag):
            v = [r for r in rows if r[1] == tag]
            if not v:
                return "%s：无样本" % tag
            cpu = [r[2] for r in v]
            gpu = [r[3] for r in v]
            return ("%s：%d 个样本  CPU 均值 %.0f%%（%.0f~%.0f）  GPU 均值 %.0f%%（%.0f~%.0f）" % (
                tag, len(v), sum(cpu) / len(cpu), min(cpu), max(cpu),
                sum(gpu) / len(gpu), min(gpu), max(gpu)))
        return "\n     ".join([stat(self.rows, "prefill"), stat(self.rows, "decode")])

    def timeline(self, step=8):
        """每隔 N 个采样打一行，直观看占用随阶段的变化。"""
        out = []
        for i in range(0, len(self.rows), step):
            chunk = self.rows[i:i + step]
            cpu = sum(r[2] for r in chunk) / len(chunk)
            gpu = sum(r[3] for r in chunk) / len(chunk)
            st = chunk[0][1]
            out.append("      t=%4ds  阶段=%-8s CPU %3.0f%%  GPU %3.0f%%" % (
                chunk[0][0], st, cpu, gpu))
        return "\n".join(out)


def wait_ready(timeout=420):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            with _opener.open(HOST + "/health", timeout=5) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(3)
    return False


def vram_line():
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,memory.total",
                              "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=20)
        u, t = out.stdout.strip().split(",")
        return "显存 %s / %s MiB" % (u.strip(), t.strip())
    except Exception:
        return "显存 n/a"


def run_case(name, ngl, extra, doc_full, out_tokens, a_target):
    print("=" * 78, flush=True)
    print("【%s】 -c %d  -ngl %d  -t %d  --cpu-moe  %s" % (
        name, CTX, ngl, THREADS, " ".join(extra) or "(KV 默认 f16)"), flush=True)
    logpath = os.path.join(LOGDIR, "kv64k_%s.log" % name.replace(" ", ""))
    os.makedirs(LOGDIR, exist_ok=True)
    args = [BIN, "--host", "127.0.0.1", "--port", str(PORT),
            "-m", MODEL, "-c", str(CTX), "-t", str(THREADS),
            "--parallel", "1", "-ngl", str(ngl), "--cpu-moe"] + list(extra)
    logf = open(logpath, "w", encoding="utf-8", errors="replace")
    p = subprocess.Popen(args, stdout=logf, stderr=subprocess.STDOUT)
    res = {}
    try:
        if not wait_ready():
            print("  [失败] 服务未就绪（多半是显存不足/层数装不下）", flush=True)
            tail = "".join(open(logpath, encoding="utf-8", errors="replace")
                           .read().splitlines(True)[-15:])
            print(tail, flush=True)
            return None
        print("  就绪，%s" % vram_line(), flush=True)

        # 文档只构造一次（要用到服务的 /tokenize 校准，所以必须在服务起来之后）
        if doc_full is None:
            target = int(a_target)
            doc, secs = build_doc(target - 512)
            doc_full = doc + LONG_Q
            ntok = tokenize(doc_full)
            print("  长文档 %d 节，提示词实际 %d token" % (secs, ntok), flush=True)

        # --- 短对话 ---
        t0 = time.time()
        r = post("/v1/chat/completions", {
            "messages": [{"role": "user", "content": SHORT_Q}],
            "max_tokens": 256, "temperature": 0.2,
            "chat_template_kwargs": {"enable_thinking": False},
        })
        t = r.get("timings") or {}
        res["short"] = (t.get("prompt_n"), t.get("prompt_per_second"),
                        t.get("predicted_n"), t.get("predicted_per_second"))
        print("  [短对话] prompt %s tok  prefill %.2f t/s | 生成 %s tok  decode %.2f t/s  (%.0fs)" % (
            t.get("prompt_n"), t.get("prompt_per_second", 0),
            t.get("predicted_n"), t.get("predicted_per_second", 0),
            time.time() - t0), flush=True)

        # --- 深上下文 ---
        print("  [深上下文] 提交中... %s" % time.strftime("%H:%M:%S"), flush=True)
        print("  （提示词 6.2 万 token，预填充约 8~9 分钟；这期间是 GPU 在算，CPU 占用天然低）",
              flush=True)
        sm = Sampler(logpath)
        sm.start()
        t0 = time.time()
        r = post("/v1/chat/completions", {
            "messages": [{"role": "user", "content": doc_full}],
            "max_tokens": out_tokens, "temperature": 0.2,
            "chat_template_kwargs": {"enable_thinking": False},
        })
        wall = time.time() - t0
        sm.stop = True
        sm.join(timeout=30)
        t = r.get("timings") or {}
        res["deep"] = (t.get("prompt_n"), t.get("prompt_per_second"),
                       t.get("predicted_n"), t.get("predicted_per_second"))
        print("  [深上下文] prompt %s tok  prefill %.2f t/s | 生成 %s tok  decode %.2f t/s  墙钟 %.0fs" % (
            t.get("prompt_n"), t.get("prompt_per_second", 0),
            t.get("predicted_n"), t.get("predicted_per_second", 0), wall), flush=True)
        print("  [占用时间线] 每 8 个采样（约 32 秒）一行：", flush=True)
        print(sm.timeline(), flush=True)
        print("  [分阶段汇总]\n     %s" % sm.report(), flush=True)
        print("  [显存] %s" % vram_line(), flush=True)
        print("  [回答开头] %s" % ((r["choices"][0]["message"].get("content") or "")
                                [:120].replace("\n", " ")), flush=True)
    finally:
        p.terminate()
        try:
            p.wait(timeout=25)
        except Exception:
            p.kill()
        logf.close()
        time.sleep(3)
    return res, doc_full


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", type=int, default=62000, help="深上下文提示词目标 token")
    ap.add_argument("--out", type=int, default=800, help="回答 token 上限")
    ap.add_argument("--only", default="", help="q8 / f16 / 空=两组都跑")
    a = ap.parse_args()

    cases = []
    if a.only in ("", "q8"):
        cases.append(("Q8  KV q8_0 · 40 层", 40, ["--cache-type-k", "q8_0",
                                                "--cache-type-v", "q8_0"]))
    if a.only in ("", "f16"):
        cases.append(("F16 KV f16   · 24 层", 24, []))

    print("目标：64K 档（-c %d）下 KV 量化对速度的影响" % CTX, flush=True)
    print("模型：%s" % os.path.basename(MODEL), flush=True)

    # 先起第一组服务，构造一次长文档，后续复用，避免重复造文档浪费时间
    doc_full = None
    allres = {}
    for name, ngl, extra in cases:
        r, doc_full = run_case(name, ngl, extra, doc_full, a.out, a.target)
        allres[name] = r

    print("=" * 78, flush=True)
    print("汇总：", flush=True)
    for name, r in allres.items():
        if not r:
            print("  %-24s 未跑成（显存不足）" % name, flush=True)
            continue
        s, d = r.get("short"), r.get("deep")
        print("  %-24s 短对话 decode %.2f t/s | 深上下文 prefill %.2f / decode %.2f t/s" % (
            name, s[3] if s else 0, d[1] if d else 0, d[3] if d else 0), flush=True)


if __name__ == "__main__":
    main()
