# -*- coding: utf-8 -*-
"""静态验证显存预算：把启动脚本里真实的预算代码抽出来，喂各种显卡规格遍历 6 个档位。

**不需要显卡，也不加载模型** —— 只跑 :BUILD_GPU_ARGS / :BGA_CALC / :NEED_FOR_CTX，
确认算出的层数、KV 精度、参数串都合法：没有负数层数、除零、越界，
40/96K/128K 这些没条件实测的档位也能据此确认「参数可用、逻辑正确、不报错」。

用途：
    - 换模型 / 换显卡后，先跑一遍确认预算不会算歪；
    - 改过 :BGA_CALC / :BUILD_GPU_ARGS 后回归。

用法：
    python _维护脚本\\check_budget.py

判读：末行「异常输出行：0」即通过；某行带 `<=` 标记说明参数串与层数不一致。
"""
import os
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BAT = os.path.join(ROOT, "启动大模型_StartModel.bat")
OUT = os.path.join(ROOT, "logs", "_budget_matrix.bat")

src = open(BAT, "rb").read().decode("gbk")
lines = src.split("\r\n")


def find(pred, start=0):
    for i in range(start, len(lines)):
        if pred(lines[i]):
            return i
    raise SystemExit("找不到目标行")


A = find(lambda l: l.strip() == ":BUILD_GPU_ARGS")
B = find(lambda l: l.strip() == ":BGA_MANUAL", A)
C0 = find(lambda l: l.startswith('set "GPU_MIN_FREE_MIB='))
C1 = find(lambda l: l.startswith('set "GPU_NLAYER='))

consts = lines[C0:C1 + 1]
body = lines[A:B]                      # :BUILD_GPU_ARGS .. :BGA_CALC .. :BGA_SMALL
needctx = None
n0 = find(lambda l: l.strip() == ":NEED_FOR_CTX")
needctx = lines[n0:find(lambda l: l.strip() == ":MEM_CHECK", n0)]

# 显卡规格：50 系（Blackwell）+ 标定卡 + 一个「只有 4 GB」的极端，看降级路径
GPUS = [
    ("RTX 5090       32GB", 32768),
    ("RTX 5080       16GB", 16384),
    ("RTX 5070 Ti    16GB", 16384),
    ("RTX 5060 Ti    16GB", 16384),
    ("RTX 5070       12GB", 12288),
    ("RTX 5060        8GB", 8192),
    ("RTX 3050        8GB", 8192),
    ("GTX 1060 标定   3GB", 3072),
]
TIERS = [(1, 16384), (2, 24576), (3, 32768), (4, 65536), (5, 98304), (6, 131072)]
DESKTOP = 300          # Windows 桌面 + 浏览器典型占用
MODEL_BYTES = 22134528992   # 官方 UD-Q4_K_M

head = ['@echo off', 'chcp 936 <nul >nul 2>nul', 'set "GPU_AVAILABLE=1"',
        'set "GPU_MODE=auto"', 'set "MMPROJ_SW=auto"',
        r'set "MMPROJ=E:\llm-cpp\llama.cpp\models\mmproj-BF16.gguf"']
script = head + consts + ['']
for name, total in GPUS:
    for tier, ctx in TIERS:
        script += [
            f'set "GPU_TOTAL_MIB={total}"',
            f'set "GPU_OTHER_MIB={DESKTOP}"',
            f'set "GPU_FREE_MIB={total - DESKTOP}"',
            f'set "MODEL_MB={MODEL_BYTES // 1048576}"',
            f'set "CTX={ctx}"',
            'call :BGA_CALC_ALL',
            f'echo R;{name};{tier};{ctx};%BGA_N%;%BGA_MMPROJ%;%BGA_KVNAME%;%BGA_KVUSED%;%BGA_AVAIL%;%GPU_ARGS%;%NEED_GB%',
            '',
        ]
# 一次性进入 auto 分支（GPU_ARGS 由 :BUILD_GPU_ARGS 产出）
script += ['set "CTX=16384"', 'exit /b 0', ''] + body + [''] + needctx
script += ['', ':BGA_CALC_ALL', 'call :BUILD_GPU_ARGS', 'call :NEED_FOR_CTX %CTX%', 'exit /b 0', '']

open(OUT, "wb").write("\r\n".join(script).encode("gbk", errors="replace"))

p = subprocess.run(["cmd", "/c", OUT], capture_output=True)
rows = [l for l in p.stdout.decode("gbk", "replace").splitlines() if l.startswith("R;")]
err = p.stdout.decode("gbk", "replace").replace("\r", "")
bad = [l for l in err.splitlines()
       if l.strip() and not l.startswith("R;") and "系统找不到" not in l]

hdr = ("显卡", "档", "ctx", "层数", "视觉塔", "KV", "KV_MiB", "可给权重", "参数", "需内存")
print(" | ".join(hdr))
print("-" * 132)
for r in rows:
    f = r.split(";")
    if len(f) < 11:
        print("!! 解析失败:", r[:80]); continue
    name, tier, ctx, n, mmp, kv, kvu, avail, args, need = f[1:11]
    if not str(n).lstrip("-").isdigit():
        print("!! 层数非法:", r[:80]); continue
    n_i = int(n)
    flag = ""
    if n_i < 0:
        flag = "  <== 负数层数！"
    if n_i >= 8 and ("--n-gpu-layers %s " % n_i) not in args + " ":
        flag = "  <== 参数串(%s)与层数(%d)不一致！" % (args.count("--n-gpu-layers") and args.split("--n-gpu-layers ")[1].split()[0], n_i)
    print(" | ".join([name, tier, ctx, n, mmp, kv, kvu, avail,
                      args.replace("--cpu-moe --parallel 1", ".."), need]) + flag)
print("-" * 132)
print("异常输出行：%d" % len(bad))
for l in bad[:10]:
    print("   ", l[:120])
