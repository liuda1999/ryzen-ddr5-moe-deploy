# -*- coding: utf-8 -*-
"""8 GB 显存档位资源重设 · 实测台架（CPU 满载度 + GPU 利用率 双采样版）

背景（2026-10-22）：RTX 2070 8 GB 跑 96K 档（-ngl 40 --n-cpu-moe 33，q8_0 KV + mmproj）
时短对话 decode 43 t/s 正常，prefill 只有 8.4 t/s（同机 64K 档历史 260 t/s）。

本项目是 CPU 重载设计：MoE 专家权重 91.9% 留在内存由 24 线程计算，prefill 又按
-ub 1024 分块送进去。所以判定标准不是单纯的 t/s，而是：
    decode 阶段 24 线程要跑满、GPU 同时尽量忙；prefill 阶段 GPU 要喂饱、CPU 按块持续有活。
本台架同时采样「llama-server 实际吃掉几个核」与「GPU 利用率」，并按阶段分开统计。

已测到的关键事实（-lv 4 日志）：
  · 96K + 专家全留 CPU + f16 KV：PP4K = 352 t/s（说明 96K 本身没问题）
  · 96K + E=7 + q8 KV + mmproj：model 4758 + KV 1020 + RS 61 + compute 660
    + mmproj 1134（日志明确写 worst-case 1134，预算常量只算了 930）+ 桌面 307
    ≈ 7940 MiB → 只剩 250 MiB 余量，深 prefill 必然越界

用法：
    python _维护脚本\\bench_8g_matrix.py --list
    python _维护脚本\\bench_8g_matrix.py --only A,B,C,D
    python _维护脚本\\bench_8g_matrix.py                 # 全部

产物：logs\\bench8g_<时间戳>\\{A..H}.log + matrix.csv + summary.txt
"""
import argparse
import base64
import csv
import json
import os
import re
import statistics
import subprocess
import sys
import threading
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BIN = os.path.join(ROOT, "llama.cpp", "build-zen5", "bin", "llama-server.exe")
MODEL = os.path.join(ROOT, "llama.cpp", "models", "Qwen3.6-35B-A3B-UD-Q4_K_M.gguf")
MMPROJ = os.path.join(ROOT, "llama.cpp", "models", "mmproj-BF16.gguf")
STAMP = time.strftime("%Y%m%d-%H%M%S")
OUTDIR = os.path.join(ROOT, "logs", "bench8g_" + STAMP)

PORT = 35110
HOST = "http://127.0.0.1:%d" % PORT
THREADS = 24
GPU_TOTAL_MIB = 8192          # RTX 2070
N_CORES = 24                  # 本机 16C/32T，脚本给 24 线程

try:
    sys.stdout.reconfigure(errors="replace")
except Exception:
    pass

for _k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
    os.environ.pop(_k, None)
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

PARA = (
    "第{i}节 本地推理工程记录：在纯中央处理器环境下部署大语言模型，"
    "需要同时权衡模型体积、量化精度与内存带宽三者之间的关系。"
    "量化把权重从十六位浮点压缩到四位整数，显著降低了内存占用和带宽压力，"
    "但也会带来一定的精度损失。多专家混合架构在推理时只激活少量专家，"
    "因此实际计算量远小于参数总量所暗示的规模，这让中央处理器推理变得可行。"
    "线程调度方面，物理核心的利用率比逻辑线程数更值得关注，"
    "因为同步开销与内存带宽争用会在高并发时抵消并行收益。"
)
SHORT_Q = "用一句话说明什么是混合专家模型。"

KVQ8 = ["--cache-type-k", "q8_0", "--cache-type-v", "q8_0"]

# A 组公共：E=1 + q8_0 KV + 视觉塔走系统内存（与当前落地配置完全一致）
A_COMMON = ["--n-cpu-moe", "39", "--mmproj", MMPROJ, "--no-mmproj-offload"] + KVQ8

# A 组胜出的开关，B 组继承（A 组结论出来后填这里）
A_WIN = []
B_COMMON = ["--mmproj", MMPROJ, "--no-mmproj-offload"] + KVQ8 + A_WIN
# B 组结论：整层专家 E=8（--n-cpu-moe 32）最优，C 组线程扫描固定用它
C_COMMON = B_COMMON + ["--n-cpu-moe", "32"]
# D/U 组用落地值：E=7（--n-cpu-moe 33）+ 16 线程
U_COMMON = B_COMMON + ["--n-cpu-moe", "33", "-t", "16", "--threads-batch", "16"]

# name, ctx, 额外参数, 说明
GROUPS = [
    ("N", 98304, ["--n-cpu-moe", "39", "--mmproj", MMPROJ, "--no-mmproj-offload"] + KVQ8,
     "当前设计配置：E=1 + q8_0 KV + 视觉塔走系统内存"),
    ("O", 98304, ["--n-cpu-moe", "39"] + KVQ8,
     "对照：E=1 + q8_0 KV，完全不载视觉塔"),
    ("P", 98304, ["--cpu-moe"] + KVQ8,
     "基准：专家全留 CPU（E=0）+ q8_0 KV"),
    ("Q", 98304, ["--n-cpu-moe", "38", "--mmproj", MMPROJ, "--no-mmproj-offload"] + KVQ8,
     "试探：E=2 时代码是否仍能保持 CPU 满载"),
    ("R", 65536, ["--n-cpu-moe", "39", "--mmproj", MMPROJ, "--no-mmproj-offload"] + KVQ8,
     "当前设计配置的 64K 档：E=1 + q8_0 KV + 视觉塔走系统内存"),
    ("S", 65536, ["--cpu-moe"] + KVQ8,
     "64K 档基准：专家全留 CPU（E=0）+ q8_0 KV"),
    ("T", 98304, ["--n-cpu-moe", "36", "--mmproj", MMPROJ, "--no-mmproj-offload"] + KVQ8,
     "逐级抬升：E=4（用掉部分空余显存）"),
    ("U", 98304, ["--n-cpu-moe", "34", "--mmproj", MMPROJ, "--no-mmproj-offload"] + KVQ8,
     "逐级抬升：E=6"),
    ("V", 98304, ["--n-cpu-moe", "32", "--mmproj", MMPROJ, "--no-mmproj-offload"] + KVQ8,
     "逐级抬升：E=8（理论余量边界）"),
    ("W", 98304, ["--n-cpu-moe", "30", "--mmproj", MMPROJ, "--no-mmproj-offload"] + KVQ8,
     "越界试探：E=10（预计贴顶，用来看崩塌长什么样）"),

    # ------------------------------------------------------------------
    # 2026-10-22 第二轮：prefill 空转根因 + 显存用尽
    # A 组：固定 96K / E=1，只切 op-offload 与 load-mode，回答
    #       「prefill 阶段 CPU 只有 2.4 核」是不是 MoE 被整块搬上 GPU 造成的
    # 公共：-c 98304 -t 24 -ub 1024 -fa on -ngl 40 --parallel 1 + q8_0 KV + 视觉塔走系统内存
    # ------------------------------------------------------------------
    ("A1", 98304, A_COMMON, "基线：E=1，默认 op-offload + 默认 mmap 加载",
     {"env": {"GGML_SCHED_DEBUG": "1"}}),
    ("A2", 98304, A_COMMON + ["--no-op-offload"],
     "只关自动卸载：MoE 应留在 CPU，prefill 走 24 线程",
     {"env": {"GGML_SCHED_DEBUG": "1"}}),
    ("A3", 98304, A_COMMON, "只改全量加载：--load-mode none（拿回 pinned/repack）",
     {"load_mode": "none"}),
    ("A4", 98304, A_COMMON + ["--no-op-offload"],
     "两者都加：组合最优？",
     {"load_mode": "none"}),

    # ------------------------------------------------------------------
    # B 组：在 A 组胜者（A3：--load-mode none）下用尽显存余量
    # ------------------------------------------------------------------
    ("B1", 98304, B_COMMON + ["--n-cpu-moe", "36"], "整层专家 E=4", {"load_mode": "none"}),
    ("B2", 98304, B_COMMON + ["--n-cpu-moe", "34"], "整层专家 E=6", {"load_mode": "none"}),
    ("B3", 98304, B_COMMON + ["--n-cpu-moe", "32"], "整层专家 E=8（理论余量边界）",
     {"load_mode": "none"}),
    ("B4", 98304, B_COMMON + ["--n-cpu-moe", "38", "--moe-cache-mib", "2048"],
     "E=2 + 专家 LRU 缓存 2 GiB", {"load_mode": "none"}),
    ("B5", 98304, B_COMMON + ["--cpu-moe", "--moe-cache-mib", "3072"],
     "E=0 + 专家 LRU 缓存 3 GiB", {"load_mode": "none"}),

    # ------------------------------------------------------------------
    # C 组：线程数扫描。B3（E=8）已经确定，decode 阶段是纯 CPU 打满 24 核，
    #       而 9950X 是 16 物理核 / 32 逻辑线程 —— 24 线程存在 SMT 争用，
    #       探一下少给线程是否反而更快（MoE 分块点积是带宽型负载）。
    # ------------------------------------------------------------------
    ("C1", 98304, C_COMMON + ["-t", "16", "--threads-batch", "16"], "16 线程 = 纯物理核",
     {"load_mode": "none"}),
    ("C2", 98304, C_COMMON + ["-t", "20"], "20 线程", {"load_mode": "none"}),
    ("C4", 98304, C_COMMON + ["-t", "28", "--threads-batch", "28"], "28 线程",
     {"load_mode": "none"}),
    ("C5", 98304, C_COMMON + ["-t", "32", "--threads-batch", "32"], "32 线程 = 全逻辑线程",
     {"load_mode": "none"}),

    # D 组：E=7 vs E=8 正面对比。预算按「非专家 40 MiB/层、专家 500 MiB/层」算，
    #       而实测是 33.9 / 479 —— 保守口径会把 96K 档压到 E=7，需确认少这一层到底差多少。
    ("D1", 98304, B_COMMON + ["--n-cpu-moe", "33", "-t", "16", "--threads-batch", "16"],
     "E=7 + 16 线程（预算保守口径算出来的档）", {"load_mode": "none"}),

    # ------------------------------------------------------------------
    # U 组：-ub（物理批大小）扫描。已定的 96K 配置下，prefill 每个 ubatch 都要把
    #       17.7 GiB 专家张量搬一遍 PCIe（op-offload 判定 batch≥32），所以 ub 越大、
    #       搬运次数越少 —— 这是 prefill 最后一个可能的大杠杆。代价是 compute 缓冲变大。
    # ------------------------------------------------------------------
    ("U1", 98304, U_COMMON + ["-ub", "1024"], "对照组：ub 1024（当前落地值）",
     {"load_mode": "none"}),
    ("U2", 98304, U_COMMON + ["-ub", "1536"], "ub 1536", {"load_mode": "none"}),
    ("U3", 98304, U_COMMON + ["-ub", "2048"], "ub 2048", {"load_mode": "none"}),
]


def post(path, payload, timeout=3600):
    req = urllib.request.Request(
        HOST + path,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with _opener.open(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def tokenize(text):
    return len(post("/tokenize", {"content": text})["tokens"])


DOC_CACHE = {}


def get_doc(target):
    if target not in DOC_CACHE:
        unit = max(1, tokenize(PARA.format(i=1)))
        need = max(1, int((target - 96) / unit))
        DOC_CACHE[target] = "".join(
            PARA.format(i=i) for i in range(1, need + 1)) + "\n\n请用一句话概括上面的内容。"
    return DOC_CACHE[target]


def wait_ready(timeout=900):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            with _opener.open(HOST + "/health", timeout=5) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(2)
        if not _proc_alive():
            return False
    return False


_proc = {"p": None}


def _proc_alive():
    p = _proc["p"]
    return p is not None and p.poll() is None


def gpu_used():
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=15)
        return int(out.stdout.strip().splitlines()[0])
    except Exception:
        return None


class GpuSampler(threading.Thread):
    """长驻 nvidia-smi -lms 采样显存与 GPU 利用率。"""

    def __init__(self):
        super().__init__(daemon=True)
        self.stop_flag = False
        self.phase = "idle"
        self.rows = []
        self.p = None

    def run(self):
        t0 = time.time()
        try:
            self.p = subprocess.Popen(
                ["nvidia-smi", "--query-gpu=memory.used,utilization.gpu",
                 "--format=csv,noheader,nounits", "-lms", "500"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
            for line in self.p.stdout:
                if self.stop_flag:
                    break
                line = line.strip()
                if not line or "," not in line:
                    continue
                try:
                    u, g = [x.strip() for x in line.split(",")[:2]]
                    self.rows.append((time.time() - t0, self.phase, int(u), int(g)))
                except ValueError:
                    continue
        except Exception:
            pass

    def reset(self, phase):
        self.phase = phase

    def peak(self, phase=None):
        v = [r[2] for r in self.rows if phase is None or r[1] == phase]
        return max(v) if v else None

    def util(self, phase):
        v = [r[3] for r in self.rows if r[1] == phase]
        return round(sum(v) / len(v), 1) if v else None

    def halt(self):
        self.stop_flag = True
        if self.p:
            try:
                self.p.terminate()
            except Exception:
                pass


class CpuSampler(threading.Thread):
    """按 PID 采样 llama-server 实际吃掉几个核 + 系统总 CPU。

    为什么必须单独测：本项目的判据是「decode 时 24 线程跑满」，
    而 prefill 阶段按 -ub 1024 分块处理，CPU 不该长时间空转。
    只看 t/s 会把「CPU 被饿着」误判成「CPU 算不动」。

    2026-10-22 三处修正：
      · 按 PID 取 TotalProcessorTime。原来按进程名，机器上只要还有第二个
        llama-server，Get-Process 会返回数组，核数直接失真；
      · 只起一个常驻 PowerShell 循环（约 1 Hz）。原来每 0.8 s 起一个
        powershell.exe，光是进程启动就要 0.5~1.5 s，prefill 这种十几秒的
        阶段只能取到两三个点；
      · 数字一律用 InvariantCulture 格式化，避免区域设置把小数点变成逗号。
    """

    def __init__(self, pid):
        super().__init__(daemon=True)
        self.pid_ = pid
        self.stop_flag = False
        self.phase = "idle"
        self.rows = []      # (t, phase, sys_pct, cores)
        self.p = None
        self.err = None

    def run(self):
        ps = (
            "$ErrorActionPreference='SilentlyContinue';"
            "$id=%d;"
            "$t0=Get-Date;"
            "$prev=(Get-Process -Id $id).TotalProcessorTime.TotalSeconds;"
            "$pt=$t0;$i=0;$sys=0;"
            "while($true){"
            " Start-Sleep -Milliseconds 900;"
            " $cur=(Get-Process -Id $id).TotalProcessorTime.TotalSeconds;"
            " $now=Get-Date;"
            " $dt=($now-$pt).TotalSeconds;"
            " if($cur -eq $null){break};"
            " $c=0.0; if($dt -gt 0.05){$c=($cur-$prev)/$dt};"
            " $i++;"
            # 系统总 CPU 的 WMI 查询在 24 线程满载时会被饿到 8 s 一次，
            # 所以 8 个周期才刷一次，其余周期复用上次的值 —— 核数按 PID 每秒更新。
            " if(($i %% 8) -eq 1){$sys=(Get-CimInstance Win32_PerfFormattedData_PerfOS_Processor"
            " -Filter \"Name='_Total'\").PercentProcessorTime};"
            " [string]::Format([Globalization.CultureInfo]::InvariantCulture,"
            "'{0:F2}|{1:F2}|{2:F0}',($now-$t0).TotalSeconds,$c,$sys);"
            " $prev=$cur;$pt=$now;"
            "}" % self.pid_
        )
        enc = base64.b64encode(ps.encode("utf-16-le")).decode("ascii")
        t0 = time.time()
        try:
            self.p = subprocess.Popen(
                ["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", enc],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, encoding="gbk", errors="replace")
            for line in self.p.stdout:
                if self.stop_flag:
                    break
                parts = line.strip().split("|")
                if len(parts) != 3:
                    continue
                try:
                    el, cores = float(parts[0]), float(parts[1])
                except ValueError:
                    continue
                try:
                    sp = float(parts[2])
                except ValueError:
                    sp = None
                self.rows.append((el, self.phase, sp, round(cores, 1)))
        except Exception as e:
            self.err = "%s: %s" % (type(e).__name__, e)

    def reset(self, phase):
        self.phase = phase

    def cores(self, phase):
        v = [r[3] for r in self.rows if r[1] == phase and r[3] is not None]
        return round(sum(v) / len(v), 1) if v else None

    def cores_max(self, phase):
        """该阶段最忙时刻吃到的核数 —— 判「能不能跑满」看它，看平均值会被首尾空转拉低。"""
        v = [r[3] for r in self.rows if r[1] == phase and r[3] is not None]
        return round(max(v), 1) if v else None

    def cores_p50(self, phase):
        v = sorted(r[3] for r in self.rows if r[1] == phase and r[3] is not None)
        if not v:
            return None
        return round(statistics.median(v), 1)

    def samples(self, phase):
        return len([r for r in self.rows if r[1] == phase])

    def sys(self, phase):
        v = [r[2] for r in self.rows if r[1] == phase and r[2] is not None]
        return round(sum(v) / len(v), 0) if v else None

    def halt(self):
        self.stop_flag = True
        if self.p:
            try:
                self.p.terminate()
            except Exception:
                pass


def parse_log(logpath):
    info = {"offload": None, "model_mib": 0.0, "kv_mib": 0.0, "compute_mib": 0.0,
            "rs_mib": 0.0, "mmproj_mib": 0.0, "oom": False}
    try:
        txt = open(logpath, encoding="utf-8", errors="replace").read()
    except Exception:
        return info
    m = re.search(r"offloaded (\d+)/(\d+) layers to GPU", txt)
    if m:
        info["offload"] = "%s/%s" % (m.group(1), m.group(2))
    m = re.search(r"estimated worst-case memory usage of mmproj is ([\d.]+) MiB", txt)
    if m:
        info["mmproj_mib"] = float(m.group(1))
    for key, pat in (("model_mib", r"CUDA0 model buffer size\s*=\s*([\d.]+) MiB"),
                     ("kv_mib", r"CUDA0 KV buffer size\s*=\s*([\d.]+) MiB"),
                     ("rs_mib", r"CUDA0 RS buffer size\s*=\s*([\d.]+) MiB"),
                     ("compute_mib", r"CUDA0 compute buffer size\s*=\s*([\d.]+) MiB")):
        vals = [float(x) for x in re.findall(pat, txt)]
        if vals:
            info[key] = max(vals) if key == "compute_mib" else round(sum(vals), 1)
    info["oom"] = ("out of memory" in txt) or ("failed to allocate compute" in txt)
    return info


def ask(content, max_tokens):
    r = post("/v1/chat/completions", {
        "messages": [{"role": "user", "content": content}],
        "max_tokens": max_tokens, "temperature": 0.0,
        "chat_template_kwargs": {"enable_thinking": False},
    })
    t = r.get("timings") or {}
    return {"prompt_n": t.get("prompt_n"), "pp": round(t.get("prompt_per_second") or 0, 2),
            "gen_n": t.get("predicted_n"), "tg": round(t.get("predicted_per_second") or 0, 2)}


def run_group(name, ctx, extra, note, args, p60=(), opts=None):
    opts = opts or {}
    print("=" * 78, flush=True)
    print("[%s] -c %d  %s\n     %s" % (name, ctx, " ".join(extra), note), flush=True)
    logpath = os.path.join(OUTDIR, name + ".log")
    cmd = [BIN, "-m", MODEL, "--host", "127.0.0.1", "--port", str(PORT),
           "-c", str(ctx), "-t", str(THREADS), "--threads-batch", str(THREADS),
           "--parallel", "1", "-ub", "1024", "-fa", "on",
           "--reasoning", "off", "-lv", "4", "-ngl", "40"] + list(extra)
    if opts.get("load_mode"):
        cmd += ["--load-mode", opts["load_mode"]]
    env = dict(os.environ)
    env.pop("LLAMA_ARG_MOE_CACHE_MIB", None)
    env.update({k: str(v) for k, v in (opts.get("env") or {}).items()})

    base = [x for x in (gpu_used() for _ in range(3)) if x]
    rec = {"group": name, "ctx": ctx, "extra": " ".join(extra), "note": note,
           "base_used": int(statistics.median(base)) if base else None, "ok": 0,
           "load_s": None, "short_tg": None, "pp4k": None, "pp16k": None, "pp60k": None,
           "deep_tg": None, "peak": None, "peak_own": None,
           "cores_short": None, "gpu_short": None,
           "cores_pp4k": None, "gpu_pp4k": None,
           "cores_deep": None, "gpu_deep": None,
           "model_mib": None, "kv_mib": None, "rs_mib": None,
           "compute_mib": None, "mmproj_mib": None, "offload": None,
           "flags": "", "err": ""}

    need = opts.get("min_free") or args.min_free
    free0 = GPU_TOTAL_MIB - (rec["base_used"] or GPU_TOTAL_MIB)
    if need and free0 < need:
        rec["err"] = "显存不足：空闲 %d MiB < 需要 %d MiB（先停掉占用显存的实例）" % (free0, need)
        print("  [跳过] %s" % rec["err"], flush=True)
        return rec

    logf = open(logpath, "w", encoding="utf-8", errors="replace")
    t_load = time.time()
    p = subprocess.Popen(cmd, stdout=logf, stderr=subprocess.STDOUT, env=env)
    _proc["p"] = p
    gs, cs = GpuSampler(), CpuSampler(p.pid)
    gs.start()
    cs.start()

    def snap(tag):
        rec["cores_" + tag] = cs.cores(tag)
        rec["cores_max_" + tag] = cs.cores_max(tag)
        rec["cores_p50_" + tag] = cs.cores_p50(tag)
        rec["gpu_" + tag] = gs.util(tag)

    try:
        if not wait_ready(opts.get("timeout", 900)):
            rec["err"] = "服务未就绪"
            print("  [失败] 服务未就绪（多半真 OOM），日志尾部：", flush=True)
            tail = open(logpath, encoding="utf-8", errors="replace").read().splitlines()[-10:]
            print("\n".join("    " + x for x in tail), flush=True)
            return rec
        rec["load_s"] = round(time.time() - t_load, 1)
        print("  就绪 %.1fs  显存 %s MiB（桌面基线 %s）" % (
            rec["load_s"], gpu_used(), rec["base_used"]), flush=True)

        gs.reset("warmup"), cs.reset("warmup")
        ask("Count from 1 to 40, one number per line.", 64)

        gs.reset("short"), cs.reset("short")
        # 生成 512 token：decode 持续约 15~20 s，才够 CPU 采样器取到 8+ 个样本算核数
        r = ask(SHORT_Q, 512)
        rec["short_tg"] = r["tg"]
        snap("short")
        print("  [短对话] decode %.2f t/s | CPU %.1f 核（峰值 %.1f 核 / 样本 %d）系统 %.0f%% | GPU %.0f%%" % (
            r["tg"], rec["cores_short"] or -1, cs.cores_max("short") or -1,
            cs.samples("short"), cs.sys("short") or -1, rec["gpu_short"] or -1), flush=True)

        gs.reset("pp4k"), cs.reset("pp4k")
        r = ask(get_doc(4096), 16)
        rec["pp4k"] = r["pp"]
        snap("pp4k")
        print("  [PP4K]  prefill %.2f t/s（%s tok）| CPU %.1f 核 / 系统 %.0f%% | GPU %.0f%% | 峰值显存 %s" % (
            r["pp"], r["prompt_n"], rec["cores_pp4k"] or -1, cs.sys("pp4k") or -1,
            rec["gpu_pp4k"] or -1, gs.peak("pp4k")), flush=True)

        if not args.skip_pp16k and r["pp"] >= 60:
            gs.reset("pp16k"), cs.reset("pp16k")
            r = ask(get_doc(16384), 16)
            rec["pp16k"] = r["pp"]
            print("  [PP16K] prefill %.2f t/s | CPU %.1f 核 | GPU %.0f%%" % (
                r["pp"], cs.cores("pp16k") or -1, gs.util("pp16k") or -1), flush=True)

            gs.reset("deep"), cs.reset("deep")
            r = ask("请用一句话概括上面文档的核心观点。", 64)
            rec["deep_tg"] = r["tg"]
            snap("deep")
            print("  [深 decode] %.2f t/s（prompt %s tok）| CPU %.1f 核 | GPU %.0f%%" % (
                r["tg"], r["prompt_n"], rec["cores_deep"] or -1, rec["gpu_deep"] or -1),
                flush=True)

            if name in p60 and r["pp"] >= 100:
                gs.reset("pp60k"), cs.reset("pp60k")
                r = ask(get_doc(61440), 16)
                rec["pp60k"] = r["pp"]
                print("  [PP60K] prefill %.2f t/s | CPU %.1f 核 | GPU %.0f%% | 峰值 %s" % (
                    r["pp"], cs.cores("pp60k") or -1, gs.util("pp60k") or -1,
                    gs.peak("pp60k")), flush=True)
        else:
            print("  [PP16K] 跳过（PP4K %.1f < 60，8 t/s 下 16K 要半小时）" % r["pp"], flush=True)

        rec["ok"] = 1
    except Exception as e:
        rec["err"] = "%s: %s" % (type(e).__name__, e)
        print("  [异常] %s" % rec["err"], flush=True)
    finally:
        gs.reset("idle")
        rec["peak"] = gs.peak()
        if rec["peak"] and rec["base_used"] is not None:
            rec["peak_own"] = max(0, rec["peak"] - rec["base_used"])
        gs.halt()
        cs.halt()
        p.terminate()
        try:
            p.wait(timeout=30)
        except Exception:
            p.kill()
        logf.close()
        time.sleep(2)
        lg = parse_log(logpath)
        rec.update({k: lg[k] for k in ("model_mib", "kv_mib", "rs_mib",
                                       "compute_mib", "mmproj_mib", "offload")})
        if lg["oom"]:
            rec["flags"] += " OOM"
        print("  [显存] model %s + KV %s + RS %s + compute %s + mmproj %s MiB，"
              "峰值 %s / 本进程 %s / 余量 %s" % (
                  rec["model_mib"], rec["kv_mib"], rec["rs_mib"], rec["compute_mib"],
                  rec["mmproj_mib"], rec["peak"], rec["peak_own"],
                  (GPU_TOTAL_MIB - rec["peak"]) if rec["peak"] else "-"), flush=True)
    return rec


def judge(rec, best_pp4k):
    flags = []
    peak = rec.get("peak") or 0
    own = rec.get("peak_own") or peak
    # 贴顶按绝对峰值判（机器上还有别人的进程时，能用的显存本来就更少）
    if peak >= GPU_TOTAL_MIB - 128:
        flags.append("A:贴顶")
    accounted = sum(x for x in (rec.get("model_mib"), rec.get("kv_mib"), rec.get("rs_mib"),
                                rec.get("compute_mib"), rec.get("mmproj_mib")) if x)
    if own and accounted and (own - accounted) > 384:
        flags.append("B:账实差%d" % int(own - accounted))
    if best_pp4k and rec.get("pp4k") and rec["pp4k"] < 0.5 * best_pp4k:
        flags.append("C:prefill崩")
    # 关键判据：CPU 没吃满而 prefill 又很慢 = CPU 被卡住（等 GPU/等 PCIe），不是算力不足
    if (rec.get("pp4k") or 999) < 120 and (rec.get("cores_pp4k") or 99) < 12:
        flags.append("D:CPU饿着")
    rec["flags"] = (rec["flags"] + " " + " ".join(flags)).strip()
    rec["verdict"] = "显存越界" if any(f[0] in "AB" for f in flags) else (
        "prefill崩" if any(f[0] == "C" for f in flags) else
        ("达标" if (rec.get("pp4k") or 0) >= 150 else "偏低"))
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--skip-pp16k", action="store_true")
    ap.add_argument("--pp60k", default="B,C", help="这些组追加 PP60K（默认 B,C）")
    ap.add_argument("--min-free", type=int, default=4500,
                    help="开跑前要求的最小空闲显存 MiB（低于此值直接跳过该组，绝不杀进程）")
    args = ap.parse_args()

    want = [x.strip() for x in args.only.split(",") if x.strip()]
    todo = [g for g in GROUPS if not want or g[0] in want]
    if want and len(todo) != len(want):
        print("未知组名：%s" % ",".join(set(want) - {g[0] for g in todo}))
        return 1
    if args.list:
        print("模型：%s\n视觉塔：%s\n端口：%d\n" % (MODEL, MMPROJ, PORT))
        for g in todo:
            print("%s  -c %-6d %-56s %s" % (g[0], g[1], " ".join(g[2]), g[3]))
        return 0

    os.makedirs(OUTDIR, exist_ok=True)
    if gpu_used() is None:
        print("nvidia-smi 不可用")
        return 1
    try:
        with _opener.open(HOST + "/health", timeout=2) as r:
            print("端口 %d 已有服务在跑，先关掉" % PORT)
            return 1
    except Exception:
        pass

    print("产物目录：%s" % OUTDIR, flush=True)
    p60 = [x.strip() for x in args.pp60k.split(",") if x.strip()]
    recs, t0 = [], time.time()
    for g in todo:
        name, ctx, extra, note = g[0], g[1], g[2], g[3]
        opts = g[4] if len(g) > 4 else {}
        recs.append(run_group(name, ctx, extra, note, args, p60, opts))

    best = max([r.get("pp4k") or 0 for r in recs] or [0])
    for r in recs:
        judge(r, best)

    keys = ["group", "ctx", "extra", "ok", "load_s", "short_tg", "pp4k", "pp16k", "pp60k",
            "deep_tg", "cores_short", "cores_max_short", "gpu_short", "cores_pp4k",
            "cores_max_pp4k", "gpu_pp4k", "cores_deep", "gpu_deep", "model_mib", "kv_mib",
            "rs_mib", "compute_mib", "mmproj_mib", "peak", "peak_own", "base_used",
            "verdict", "flags", "err"]
    csv_path = os.path.join(OUTDIR, "matrix.csv")
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        for r in recs:
            w.writerow({k: r.get(k) for k in keys})

    lines = ["%-2s %-5s %-30s %7s %7s %6s %6s %6s %6s %6s %6s  %s" % (
        "组", "ctx", "配置", "decode", "PP4K", "DC均核", "DC峰核", "PP均核", "PP峰核",
        "GPU%", "余量", "判定")]
    for r in recs:
        slack = (GPU_TOTAL_MIB - (r.get("peak") or 0)) if r.get("peak") else None
        lines.append("%-2s %-5d %-30s %7.1f %7.1f %6s %6s %6s %6s %6s %6s  %s %s" % (
            r["group"], r["ctx"], (r["extra"] or "")[:30],
            r.get("short_tg") or 0, r.get("pp4k") or 0,
            r.get("cores_short") or "-", r.get("cores_max_short") or "-",
            r.get("cores_pp4k") or "-", r.get("cores_max_pp4k") or "-",
            r.get("gpu_pp4k") or "-",
            slack if slack is not None else "-",
            r.get("verdict") or "-", r.get("flags") or ""))
    txt = "\n".join(lines)
    open(os.path.join(OUTDIR, "summary.txt"), "w", encoding="utf-8").write(txt + "\n")
    print("\n" + "=" * 78, flush=True)
    print(txt, flush=True)
    print("\n（DC核 = 短对话 decode 阶段 llama-server 平均占用核数；"
          "PP核 = PP4K 预填充阶段平均占用核数；本机给 24 线程，理论上限 24 核 / 系统 75%）", flush=True)
    print("总耗时 %.1f 分钟；CSV: %s" % ((time.time() - t0) / 60, csv_path), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
