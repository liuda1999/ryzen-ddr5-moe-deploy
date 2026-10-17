# -*- coding: utf-8 -*-
"""8 GB 基准 · CPU 真实占用验证（系统级计数器版）

为什么重做：
  之前的台架每轮采样都新起一个 powershell.exe（0.3~0.6 s 启动开销），
  采样点稀疏、且 Win32_PerfFormattedData 在非持续刷新下可能返回陈旧值，
  得到的「23.5 核」无法与任务管理器逐秒对上。

本脚本改用 typeperf（PDH 持续采样，与任务管理器同一数据源）：
  1) \\Processor(_Total)\\% Processor Time      —— 系统总占用，就是任务管理器那个数
  2) \\Process(llama-server)\\% Processor Time  —— 进程占用，相对单核，2400 = 24 个核
每秒一行，原始 CSV 全保留，可自己逐行核对。

负载设计（目的是让 CPU 尽可能长时间压在高位）：
  P1 连续 prefill ×6 —— 每次独立 4K 文档，prefill 并行度最高，CPU 最容易跑满
  P2 长生成 decode ×2 —— 512 token，看单 token 路径能吃几个核
  P3 深上下文 —— 逐步累到 40K 以上再 prefill + decode
  P4 收尾 4K prefill —— 确认没有随时间劣化

用法（服务需已由 启动大模型_StartModel.bat start 拉起）：
    python _维护脚本\\verify_cpu.py                 # 默认 8G/96K
    python _维护脚本\\verify_cpu.py --port 35035
"""
import argparse
import csv
import json
import os
import random
import re
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
STAMP = time.strftime("%Y%m%d-%H%M%S")
OUTDIR = os.path.join(ROOT, "logs", "cpuverify_" + STAMP)

for _k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
    os.environ.pop(_k, None)
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

try:
    sys.stdout.reconfigure(errors="replace")
except Exception:
    pass

PARA = (
    "第{i}节 本地推理工程记录：在纯中央处理器环境下部署大语言模型，"
    "需要同时权衡模型体积、量化精度与内存带宽三者之间的关系。"
    "量化把权重从十六位浮点压缩到四位整数，显著降低了内存占用和带宽压力，"
    "但也会带来一定的精度损失。多专家混合架构在推理时只激活少量专家，"
    "因此实际计算量远小于参数总量所暗示的规模，这让中央处理器推理成为可行方案。"
    "线程调度方面，物理核心的利用率比逻辑线程数更值得关注，"
    "因为同步开销与内存带宽争用会在高并发时抵消并行收益。"
)

HOST = None
API_KEY = ""


def post(path, payload, timeout=3600):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(HOST + path, data=body,
                                 headers={"Content-Type": "application/json"})
    if API_KEY:
        req.add_header("Authorization", "Bearer " + API_KEY)
    with _opener.open(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def get(path, timeout=30):
    req = urllib.request.Request(HOST + path)
    if API_KEY:
        req.add_header("Authorization", "Bearer " + API_KEY)
    with _opener.open(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def tok_n(text):
    return len(post("/tokenize", {"content": text})["tokens"])


_SALT_TAG = "甲乙丙丁戊己庚辛壬癸子丑寅卯辰巳午未申酉戌亥天地玄黄宇宙洪荒"


def get_doc(target, salt=0):
    """拼出一段 token 数 >= target 的中文长文。

    salt 必须每份不同：llama-server 会按相同前缀复用 KV（prompt cache），
    用同一份文档连打多次时，第 2 次起会直接命中缓存、跳过 prefill，
    于是 CPU 看起来「没干活」——这是上一轮实测的假象来源。
    """
    tag = _SALT_TAG[salt % len(_SALT_TAG)] + str(salt)
    reps = 1
    while True:
        text = tag + "".join(PARA.format(i=r * 1000 + salt * 137 + k)
                             for r in range(reps) for k in range(10))
        if tok_n(text) >= target:
            return text
        reps += 1
        if reps > 400:
            return text


def ask(content, max_tokens):
    r = post("/v1/chat/completions", {
        "messages": [{"role": "user", "content": content}],
        "max_tokens": max_tokens, "temperature": 0.0,
        "chat_template_kwargs": {"enable_thinking": False},
    })
    t = r.get("timings") or {}
    return {
        "prompt_n": t.get("prompt_n") or 0,
        "pp": round(t.get("prompt_per_second") or 0, 2),
        "gen_n": t.get("predicted_n") or 0,
        "tg": round(t.get("predicted_per_second") or 0, 2),
    }


def chat(msgs, max_tokens):
    """多轮对话：返回 (timings, content)。深上下文必须走这条，否则每次都是新对话。"""
    r = post("/v1/chat/completions", {
        "messages": msgs, "max_tokens": max_tokens, "temperature": 0.0,
        "chat_template_kwargs": {"enable_thinking": False},
    })
    t = r.get("timings") or {}
    content = ""
    try:
        content = r["choices"][0]["message"]["content"] or ""
    except Exception:
        pass
    return {
        "prompt_n": t.get("prompt_n") or 0,
        "pp": round(t.get("prompt_per_second") or 0, 2),
        "gen_n": t.get("predicted_n") or 0,
        "tg": round(t.get("predicted_per_second") or 0, 2),
    }, content


def wait_ready(timeout=900):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            with _opener.open(HOST + "/health", timeout=5) as r:
                if r.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(2)
    return False


def launch_via_bat(tier, logpath):
    """用项目自己的 bat 启动（真实链路），并把整个进程树挂在当前进程下。

    必须由本进程持有 bat，否则父 shell 退出时 Windows 会连带回收
    llama-server（实测：bat 报告启动成功后进程立刻消失）。
    """
    bat = os.path.join(ROOT, "启动大模型_StartModel.bat")
    outf = open(logpath, "wb")
    p = subprocess.Popen(
        ["cmd", "/c", bat, "start", str(tier)],
        cwd=ROOT, stdin=subprocess.PIPE, stdout=outf, stderr=subprocess.STDOUT,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        # 脚本会问「是否生成新的 API Key?(y/N)」，答 n 保留现有密钥
        p.stdin.write(b"n\nn\nn\n")
        p.stdin.flush()
        p.stdin.close()
    except Exception:
        pass
    return p, outf


class TypePerf:
    """单进程持续采样，1 秒一行，原始 CSV 落盘。"""

    def __init__(self, out_csv, proc_name="llama-server"):
        self.out = out_csv
        self.proc = proc_name
        self.p = None
        self.t0 = None

    def start(self):
        counters = [
            r"\Processor(_Total)\% Processor Time",
            r"\Process(%s)\%% Processor Time" % self.proc,
        ]
        # -sc 给足上限（20 分钟），实际按需 kill
        cmd = ["typeperf"] + counters + ["-si", "1", "-sc", "1200",
                                          "-f", "CSV", "-o", self.out, "-y"]
        self.t0 = time.time()
        self.p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL,
                                  creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

    def stop(self):
        if self.p and self.p.poll() is None:
            self.p.terminate()
            try:
                self.p.wait(timeout=5)
            except Exception:
                self.p.kill()


def read_csv(path):
    """返回 (rows, base_epoch)。rows = [(elapsed_s, sys_pct, proc_pct)]，
    proc_pct 为相对单核（2400 ≈ 24 核）。"""
    rows = []
    if not os.path.exists(path):
        return rows, None
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        rd = list(csv.reader(f))
    if len(rd) < 2:
        return rows, None
    head = rd[0]
    # 列名形如 "\\PC\Processor(_Total)\% Processor Time"
    i_sys = next((i for i, h in enumerate(head) if "Processor(_Total)" in h), None)
    i_prc = next((i for i, h in enumerate(head)
                  if "Process(" in h and "_Total" not in h), None)
    base = None
    for r in rd[1:]:
        need = max([x for x in (i_sys, i_prc, 0) if x is not None])
        if len(r) <= need:
            continue
        ts = r[0].strip('"')
        try:
            t = time.mktime(time.strptime(ts.split(".")[0], "%m/%d/%Y %H:%M:%S"))
        except Exception:
            continue
        if base is None:
            base = t

        def num(i):
            if i is None:
                return None
            v = r[i].strip().strip('"')
            try:
                f = float(v)
                return f if f >= 0 else None
            except Exception:
                return None

        rows.append((round(t - base, 1), num(i_sys), num(i_prc)))
    return rows, base


def stats(vals):
    vals = [v for v in vals if v is not None]
    if not vals:
        return None
    vals_sorted = sorted(vals)
    return {
        "n": len(vals),
        "mean": round(sum(vals) / len(vals), 1),
        "median": round(vals_sorted[len(vals_sorted) // 2], 1),
        "min": round(min(vals), 1),
        "max": round(max(vals), 1),
        "p10": round(vals_sorted[int(len(vals_sorted) * 0.1)], 1),
        "p90": round(vals_sorted[min(len(vals_sorted) - 1, int(len(vals_sorted) * 0.9))], 1),
    }


def longest_run(vals, thr):
    """最长连续 >= thr 的秒数。"""
    best = cur = 0
    for v in vals:
        if v is not None and v >= thr:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


def read_api_key():
    p = os.path.join(ROOT, "api-key.txt")
    if not os.path.exists(p):
        return ""
    for ln in open(p, "rb").read().decode("gbk", errors="replace").splitlines():
        s = ln.strip()
        if s and not s.startswith("#"):
            return s
    return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=35035)
    ap.add_argument("--key", default="")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--launch", action="store_true", help="用项目 bat 启动服务")
    ap.add_argument("--tier", type=int, default=4, help="档位号（4=96K, 3=64K）")
    ap.add_argument("--stop-after", action="store_true", help="测完关闭服务")
    ap.add_argument("--decode-sec", type=float, default=45,
                    help="P2 连续生成时长（秒），用于验证长时间 CPU 占用")
    ap.add_argument("--phases", default="P0,P1,P2,P3,P4",
                    help="要跑的阶段，逗号分隔；只测长生成用 --phases P2")
    args = ap.parse_args()

    global HOST, API_KEY
    HOST = "http://%s:%d" % (args.host, args.port)
    API_KEY = args.key or read_api_key()

    os.makedirs(OUTDIR, exist_ok=True)
    print("=" * 78)
    print("输出目录：%s" % OUTDIR)
    print("目标服务：%s" % HOST)

    bat_p = None
    bat_log = None
    if args.launch:
        bl = os.path.join(OUTDIR, "bat_start.txt")
        print("[启动] 调用 启动大模型_StartModel.bat start %d（项目自己的链路）" % args.tier)
        bat_p, bat_out = launch_via_bat(args.tier, bl)
        bat_log = bl
        if not wait_ready(900):
            print("[失败] 服务 900 秒内未就绪，bat 输出见 %s" % bl)
            try:
                tail = open(bl, "rb").read().decode("gbk", errors="replace")[-2000:]
                print(tail)
            except Exception:
                pass
            return 2
        print("[就绪] bat 启动成功")
    elif not wait_ready(60):
        print("[失败] 服务未就绪，请先用 启动大模型_StartModel.bat start 拉起")
        return 2

    # 确认没有 api key 拦截
    try:
        get("/v1/models")
    except Exception as e:
        if "401" in str(e) or "403" in str(e):
            print("[失败] 需要 API key，请用 --key 传入")
            return 2

    print("[就绪] 等预热（bat 的 WARMUP）结束后再开始采样")
    time.sleep(20)

    csv_path = os.path.join(OUTDIR, "cpu_raw.csv")
    tp = TypePerf(csv_path)
    phases = []   # (name, t_start_epoch, t_end_epoch, note)
    results = []

    def phase(name, note):
        class _Ctx:
            def __enter__(self):
                self.t = time.time()
                print("── %s：%s" % (name, note), flush=True)
                return self
            def __exit__(self, *a):
                dt = time.time() - self.t
                phases.append((name, self.t, time.time(), note))
                print("   （耗时 %.0f 秒）\n" % dt, flush=True)
        return _Ctx()

    tp.start()
    time.sleep(2)

    # P0：空闲基线 —— 用来证明计数器确实在动，而不是一直报同一个数
    with phase("P0-空闲基线", "服务空转不接请求，作为对照"):
        time.sleep(10)

    docs = [get_doc(4096, salt=i) for i in range(8)]
    print("   已准备 8 份互不相同的 4K 文档（避免 prompt cache 命中）\n", flush=True)

    # P1：连续 4K prefill —— 每份文档都不同，强制真跑 prefill
    with phase("P1-连续prefill", "8 份不同 4K 文档，每次都是真 prefill"):
        for i, d in enumerate(docs):
            r = ask(d + "\n\n请只回答：收到。", 8)
            results.append(("P1", r))
            print("   [%d/8] prompt %d tok  prefill %.1f t/s  decode %.1f t/s"
                  % (i + 1, r["prompt_n"], r["pp"], r["tg"]), flush=True)

    # P2：长生成 decode —— 按时间连续跑，用于回答「CPU 能否长时间压在 70% 以上」
    with phase("P2-长生成decode", "连续生成 %.0f 秒，观察持续性" % args.decode_sec):
        t_end = time.time() + args.decode_sec
        k = 0
        while time.time() < t_end:
            k += 1
            r = ask("请详细解释混合专家模型的工作原理，并说明为什么它适合在 CPU 上推理。"
                    "请分十点展开，每点都要有具体例子。", 1024)
            results.append(("P2", r))
            print("   [%d] 生成 %d tok  decode %.1f t/s  （已跑 %.0f/%.0f 秒）"
                  % (k, r["gen_n"], r["tg"], args.decode_sec - (t_end - time.time()),
                     args.decode_sec), flush=True)

    # P3：深上下文 —— 同一对话里先灌 40K，再在深 KV 上生成
    with phase("P3-深上下文40K", "同一对话一次 40K prefill，再在深上下文上 decode"):
        doc40k = get_doc(40960, salt=90)
        msgs = [{"role": "user", "content": doc40k + "\n\n请只回答：收到。"}]
        r1, ans1 = chat(msgs, 8)
        results.append(("P3", r1))
        print("   40K prefill：prompt %d tok  %.1f t/s" % (r1["prompt_n"], r1["pp"]), flush=True)
        msgs.append({"role": "assistant", "content": (ans1 or "收到。").strip()[:40]})
        msgs.append({"role": "user", "content": "请用 300 字概括上面这份文档的主题与结构。"})
        r2, _ = chat(msgs, 300)
        results.append(("P3", r2))
        print("   深上下文 decode：prompt %d tok  生成 %d tok  %.1f t/s"
              % (r2["prompt_n"], r2["gen_n"], r2["tg"]), flush=True)

    # P4：收尾再打一次独立 4K，确认没有劣化
    with phase("P4-收尾prefill", "换一份新 4K 文档，确认未随时间劣化"):
        for i in range(2):
            r = ask(get_doc(4096, salt=200 + i) + "\n\n请只回答：收到。", 8)
            results.append(("P4", r))
            print("   [%d/2] prompt %d tok  prefill %.1f t/s" % (i + 1, r["prompt_n"], r["pp"]),
                  flush=True)

    time.sleep(3)   # 尾部空闲基线
    tp.stop()
    time.sleep(1)

    rows, base_epoch = read_csv(csv_path)
    if not rows:
        print("[失败] 没有采到计数器数据，检查 typeperf 是否可用")
        return 3
    if base_epoch is None:
        base_epoch = tp.t0

    print("=" * 78)
    print("采样点：%d 个（1 秒间隔，typeperf / PDH，与任务管理器同源）" % len(rows))
    print("原始数据：%s" % csv_path)
    n_core = os.cpu_count() or 32
    print("这是 %d 逻辑核机器，脚本给 llama-server %d 线程 → 系统占用率上限 = %.1f%%"
          % (n_core, 24, 24.0 / n_core * 100))

    print("\n%-18s %6s %7s %7s %7s %7s %9s %9s" % (
        "阶段", "秒数", "均值%", "中位%", "峰值%", "P10%", "≥70%秒数", "最长连续"))
    print("-" * 78)
    all_sys = []
    summary = {}
    for name, t0, t1, note in phases:
        sel = [r for r in rows if (t0 - base_epoch - 0.6) <= r[0] <= (t1 - base_epoch + 0.6)]
        sysv = [r[1] for r in sel]
        prcv = [(r[2] / 100.0) if r[2] is not None else None for r in sel]
        st = stats(sysv)
        if not st:
            print("%-18s （无样本）" % name)
            continue
        n70 = sum(1 for v in sysv if v is not None and v >= 70)
        lr = longest_run(sysv, 70)
        all_sys.extend([v for v in sysv if v is not None])
        pst = stats(prcv)
        summary[name] = {"sys": st, "cores": pst, "n70": n70,
                         "longest70": lr, "secs": st["n"]}
        print("%-18s %6d %7.1f %7.1f %7.1f %7.1f %9d %9d" % (
            name, st["n"], st["mean"], st["median"], st["max"], st["p10"], n70, lr))

    print("-" * 78)
    st_all = stats(all_sys)
    if st_all:
        print("%-18s %6d %7.1f %7.1f %7.1f %7.1f %9d %9d" % (
            "全程", st_all["n"], st_all["mean"], st_all["median"], st_all["max"],
            st_all["p10"], sum(1 for v in all_sys if v >= 70), longest_run(all_sys, 70)))

    print("\n各阶段 llama-server 实际占用核数（进程 % / 100）：")
    for name in summary:
        st = summary[name]["cores"]
        if st:
            print("  %-18s 均值 %.1f 核  中位 %.1f  峰值 %.1f（上限 24）"
                  % (name, st["mean"], st["median"], st["max"]))

    # 逐秒序列（前 200 行给贴出来核对）
    print("\n逐秒原始序列（时间轴相对采样开始，秒 | 系统% | 进程核数）：")
    for r in rows[:200]:
        print("  %5.0f | %5s | %5s" % (
            r[0],
            ("%.0f" % r[1]) if r[1] is not None else "-",
            ("%.1f" % (r[2] / 100.0)) if r[2] is not None else "-"))

    with open(os.path.join(OUTDIR, "phase_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    with open(os.path.join(OUTDIR, "requests.tsv"), "w", encoding="utf-8") as f:
        f.write("phase\tprompt_n\tpp_tps\tgen_n\ttg_tps\n")
        for ph, r in results:
            f.write("%s\t%d\t%.2f\t%d\t%.2f\n" % (ph, r["prompt_n"], r["pp"], r["gen_n"], r["tg"]))

    print("\n产物：%s" % OUTDIR)

    if args.stop_after:
        print("\n[关闭] 调用 启动大模型_StartModel.bat stop")
        subprocess.run(["cmd", "/c", os.path.join(ROOT, "启动大模型_StartModel.bat"), "stop"],
                       cwd=ROOT, capture_output=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    elif bat_p is not None:
        print("\n[保留] 服务继续运行（PID 见上），需要关闭时执行：启动大模型_StartModel.bat stop")

    return 0


if __name__ == "__main__":
    sys.exit(main())
