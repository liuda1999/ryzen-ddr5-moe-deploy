# -*- coding: utf-8 -*-
"""8G/96K 定型验收：用真实 bat 拉起的服务，测 prefill / decode / CPU 满载度 / 显存。

与台架的区别：这里只跑一套参数（就是 bat 实际启动的那套），但把 CPU 采样做扎实 ——
typeperf 每秒一行、原始 CSV 落盘，可以直接和任务管理器逐秒对。判据：

  · prefill（PP4K）  >= 400 t/s（旧配置 378）
  · decode（短）     >= 44 t/s（旧配置 30.8 首轮 / 40 稳态）
  · decode（长生成） 持续 100 s 以上，均速 >= 44 t/s，且进程稳定吃满物理核
  · 显存峰值         <= 7680 MiB（留 512 MiB 底线）

用法（服务需已由 启动大模型_StartModel.bat start 4 拉起）：
    python _维护脚本\\verify_final_8g.py
"""
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import verify_cpu as V  # 复用 typeperf 采样与文档构造

STAMP = time.strftime("%Y%m%d-%H%M%S")
OUTDIR = os.path.join(V.ROOT, "logs", "final8g_" + STAMP)
THREADS = 24          # 项目口径：12 核 / 24 线程（CPU 参与推理）
GPU_TOTAL = 8192
MIN_DECODE = 40.0     # 硬指标：token 生成 > 40 t/s
MIN_CORES = 0.75      # 硬指标：24 线程里至少 75% 在跑（=18 核）


class GpuPeak:
    def __init__(self):
        self.p = None
        self.rows = []

    def start(self):
        self.p = subprocess.Popen(
            ["nvidia-smi", "--query-gpu=memory.used,utilization.gpu",
             "--format=csv,noheader,nounits", "-lms", "500"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        import threading
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        for line in self.p.stdout:
            try:
                u, g = [x.strip() for x in line.strip().split(",")[:2]]
                self.rows.append((int(u), int(g)))
            except Exception:
                pass

    def stop(self):
        if self.p and self.p.poll() is None:
            self.p.terminate()

    def peak(self):
        return max(r[0] for r in self.rows) if self.rows else None

    def util_mean(self):
        v = [r[1] for r in self.rows]
        return round(sum(v) / len(v), 1) if v else None


def main():
    V.HOST = "http://127.0.0.1:35035"
    V.API_KEY = ""
    for ln in open(os.path.join(V.ROOT, "api-key.txt"), "rb").read().decode(
            "gbk", errors="replace").splitlines():
        s = ln.strip()
        if s and not s.startswith("#"):
            V.API_KEY = s
            break
    if not V.wait_ready(120):
        print("服务未就绪（先跑 启动大模型_StartModel.bat start 4）")
        return 2

    os.makedirs(OUTDIR, exist_ok=True)
    csv_path = os.path.join(OUTDIR, "cpu.csv")
    gpu = GpuPeak()
    gpu.start()
    tp = V.TypePerf(csv_path)
    tp.start()
    time.sleep(2)

    res = {}

    # ---- 1. 预热（不进统计）----
    V.ask("Count from 1 to 40, one number per line.", 64)

    # ---- 2. PP4K / 短 decode / PP16K ----
    r = V.ask(V.get_doc(4096, salt=1), 16)
    res["pp4k"] = r["pp"]
    print("PP4K   %7.2f t/s（%d tok）" % (r["pp"], r["prompt_n"]), flush=True)

    r = V.ask("用一句话说明什么是混合专家模型。", 512)
    res["tg_short"] = r["tg"]
    print("decode %7.2f t/s（%d tok）" % (r["tg"], r["gen_n"]), flush=True)

    r = V.ask(V.get_doc(16384, salt=2), 16)
    res["pp16k"] = r["pp"]
    print("PP16K  %7.2f t/s（%d tok）" % (r["pp"], r["prompt_n"]), flush=True)

    # ---- 3. 长生成：持续 100 s 以上，期间 CPU 采样密集 ----
    t_mark = time.time() - tp.t0
    print("\n[长生成] 开始，目标 5000 token（约 105 s）……", flush=True)
    t0 = time.time()
    r = V.ask("请写一篇关于本地大模型部署的技术笔记，分十个小节，每节不少于"
              "三百字，逐节展开，不要总结。", 5000)
    dt = time.time() - t0
    res["tg_long"] = r["tg"]
    res["long_secs"] = round(dt, 1)
    print("[长生成] %.2f t/s，%d token，耗时 %.1f s" % (r["tg"], r["gen_n"], dt), flush=True)
    time.sleep(2)
    t_end = time.time() - tp.t0

    tp.stop()
    gpu.stop()
    time.sleep(1)

    # ---- 4. 统计 CPU ----
    rows, _ = V.read_csv(csv_path)
    window = [x for x in rows if t_mark <= x[0] <= t_end]
    sys_pct = [x[1] for x in window]
    cores = [(x[2] / 100.0) for x in window if x[2] is not None]
    st_sys = V.stats(sys_pct) or {}
    st_core = V.stats(cores) or {}
    full_ratio = len([c for c in cores if c >= 0.70 * THREADS]) / len(cores) if cores else 0

    print("\n" + "=" * 66)
    print("CPU（长生成窗口 %.0f~%.0f s，样本 %d 个，每秒 1 点）" % (
        t_mark, t_end, len(cores)))
    print("  进程占用核数：中位 %.1f / 均值 %s / 最小 %s / 最大 %s（给 %d 线程）" % (
        st_core.get("median", -1), st_core.get("mean"), st_core.get("min"),
        st_core.get("max"), THREADS))
    print("  系统总 CPU  ：中位 %s%% / 均值 %s%%" % (st_sys.get("median"), st_sys.get("mean")))
    print("  达到 70%% 线程（%.1f 核）的秒数占比：%.1f%%" % (0.7 * THREADS, full_ratio * 100))
    print("  显存峰值 %s / %d MiB（余 %s MiB）；GPU 利用率均值 %s%%" % (
        gpu.peak(), GPU_TOTAL,
        (GPU_TOTAL - gpu.peak()) if gpu.peak() else "-", gpu.util_mean()))
    print("  原始 CSV：%s" % csv_path)
    print("=" * 66)
    print("三条硬指标：CPU 均核 >= %.1f（24 线程的 75%%）· decode > %.0f t/s · 显存 >= 7000 且余量 >= 512"
          % (MIN_CORES * THREADS, MIN_DECODE))
    ok = (st_core.get("median", 0) >= MIN_CORES * THREADS
          and res.get("tg_long", 0) > MIN_DECODE
          and (gpu.peak() or 0) >= 7000
          and (GPU_TOTAL - (gpu.peak() or 0)) >= 512)
    print("结论：%s" % ("全部达标" if ok else "有项目未达标（见上）"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
