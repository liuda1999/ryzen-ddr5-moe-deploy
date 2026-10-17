# -*- coding: utf-8 -*-
"""8 GB 基准 · 长时间连续生成下的 CPU 占用验证

目的单一：回答「decode 阶段 CPU 能不能长时间压在 70% 以上」。
不换参数、不改配置、不测别的，只用当前配置连续生成 N 秒，
期间用 typeperf（与任务管理器同源）逐秒采样。

用法：
    python _维护脚本\\verify_long_decode.py --launch --sec 120
    python _维护脚本\\verify_long_decode.py --sec 120        # 服务已在跑
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import verify_cpu as V   # noqa: E402


def arg(name, default=None, cast=str):
    if name in sys.argv:
        i = sys.argv.index(name)
        if i + 1 < len(sys.argv):
            return cast(sys.argv[i + 1])
    return default


def main():
    sec = arg("--sec", 120.0, float)
    tier = arg("--tier", 4, int)
    launch = "--launch" in sys.argv

    V.HOST = "http://127.0.0.1:%d" % arg("--port", 35035, int)
    V.API_KEY = arg("--key", "") or V.read_api_key()
    os.makedirs(V.OUTDIR, exist_ok=True)
    print("输出目录：%s" % V.OUTDIR)

    if launch:
        print("[启动] 启动大模型_StartModel.bat start %d" % tier)
        V.launch_via_bat(tier, os.path.join(V.OUTDIR, "bat_start.txt"))
        if not V.wait_ready(900):
            print("[失败] 服务未就绪")
            return 2
        print("[就绪] 等预热结束")
        time.sleep(20)
    elif not V.wait_ready(60):
        print("[失败] 服务未就绪")
        return 2

    csv_path = os.path.join(V.OUTDIR, "cpu_long.csv")
    tp = V.TypePerf(csv_path)
    tp.start()
    time.sleep(3)

    print("\n── 连续生成 %.0f 秒（当前配置，不改任何参数）" % sec, flush=True)
    t0 = time.time()
    t_end = t0 + sec
    k = 0
    tps = []
    while time.time() < t_end:
        k += 1
        r = V.ask("请详细解释混合专家模型的工作原理，并说明为什么它适合在 CPU 上推理。"
                  "请分十点展开，每点都要有具体例子。", 1024)
        tps.append(r["tg"])
        print("   [%d] 生成 %d tok  decode %.1f t/s  已跑 %.0f 秒"
              % (k, r["gen_n"], r["tg"], time.time() - t0), flush=True)

    time.sleep(3)
    tp.stop()
    time.sleep(1)

    rows, base = V.read_csv(csv_path)
    if not rows:
        print("[失败] 未采到数据")
        return 3
    if base is None:
        base = tp.t0

    sel = [r for r in rows if (t0 - base - 1) <= r[0] <= (t_end - base + 1)]
    sysv = [r[1] for r in sel if r[1] is not None]
    cores = [(r[2] / 100.0) for r in sel if r[2] is not None]

    print("\n" + "=" * 70)
    print("连续生成 %.0f 秒 · 系统 CPU（typeperf，与任务管理器同源）" % sec)
    print("采样点：%d（1 秒 1 次）   原始数据：%s" % (len(rows), csv_path))
    n_core = os.cpu_count() or 32
    print("本机 %d 逻辑核，给 llama-server 24 线程 → 占用率上限 %.1f%%"
          % (n_core, 24.0 / n_core * 100))
    if sysv:
        ss = V.stats(sysv)
        n70 = sum(1 for v in sysv if v >= 70)
        print("\n系统占用：均值 %.1f%%  中位 %.1f%%  最低 %.1f%%  最高 %.1f%%"
              % (ss["mean"], ss["median"], ss["min"], ss["max"]))
        print("  ≥70%% 的秒数：%d / %d（%.0f%%）   最长连续：%d 秒"
              % (n70, len(sysv), 100.0 * n70 / len(sysv), V.longest_run(sysv, 70)))
        for thr in (65, 70, 72, 74):
            print("  ≥%d%%：%d 秒（%.0f%%）" % (thr, sum(1 for v in sysv if v >= thr),
                                              100.0 * sum(1 for v in sysv if v >= thr) / len(sysv)))
    if cores:
        cs = V.stats(cores)
        print("\nllama-server 占用：均值 %.1f 核  中位 %.1f  最低 %.1f  最高 %.1f（上限 24）"
              % (cs["mean"], cs["median"], cs["min"], cs["max"]))
    if tps:
        print("\n生成速度：均值 %.1f t/s（%d 轮，共 %d token）"
              % (sum(tps) / len(tps), len(tps), len(tps) * 1024))

    print("\n逐秒序列（秒 | 系统%% | 进程核数）：")
    for r in rows:
        print("  %5.0f | %5s | %5s" % (
            r[0],
            ("%.0f" % r[1]) if r[1] is not None else "-",
            ("%.1f" % (r[2] / 100.0)) if r[2] is not None else "-"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
