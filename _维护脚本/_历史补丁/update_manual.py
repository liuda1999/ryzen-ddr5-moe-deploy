# -*- coding: utf-8 -*-
"""给参数阶梯手册补 CPU 平台声明，并把过期的 llm N 命令改为新的中文脚本命令。"""
import io

P = r"E:\llm-cpp\参数阶梯手册.md"
s = io.open(P, encoding='utf-8').read()

# 1) 环境行补 CPU 型号
old_env = "> 本机环境：Windows 原生 / 仅 CPU（不使用显卡）/ 16 物理核 32 逻辑核 / 内存 61.6 GB"
new_env = "> 本机环境：Windows 原生 / 仅 CPU（不使用显卡）/ **AMD Ryzen 9 9950X**（Zen 5，16 物理核 32 逻辑核）/ 内存 61.6 GB"
assert old_env in s, "环境行未匹配"
s = s.replace(old_env, new_env, 1)

# 2) 插入平台声明（紧跟环境块之后）
PLATFORM = """
---

## 平台声明（换 CPU 前必读）

本手册全部数据来自 **AMD Ryzen 9 9950X（Zen 5）** 实测。
**若换到 Intel 平台，必须做对应调整，不能直接照搬这里的数值与参数：**

1. **不需要重新编译。** 当前构建方式是"编译全部 CPU 变体 + 运行时自动择优"，
   换 Intel CPU 会自动命中该平台对应的变体。
2. **但档位速度表要重测。** 本机命中的是 `ggml-cpu-icelake`（AVX-512 + VNNI + VBMI）。
   若 Intel CPU 不支持 AVX-512（12/13/14 代酷睿消费级已被屏蔽），会回退到 AVX2 变体，
   生成速度明显下降，本手册的 t/s 数值不再适用。
3. **线程数要按物理核数重定。** 手册的 24 线程是按本机 16 物理核（取其 12 核）定的；
   换成 8 核 CPU 建议 12 线程左右，照搬 24 只会因线程争用变慢。
4. **`cascadelake` 变体的禁用有前提。** 本机为了强制走 icelake，把
   `ggml-cpu-cascadelake.dll` 改名为 `.disabled`；若换到"支持 AVX-512 但不支持 VBMI"
   的 Intel（如 Cascade Lake 至强），需把它改回 `.dll`，否则会掉到更低的变体。

换平台后建议重跑一次 `_维护脚本/run_matrix.sh` 再填档位。
"""
anchor = "\n---\n\n## 0. 当前默认配置"
assert anchor in s, "0 节锚点未匹配"
s = s.replace(anchor, PLATFORM + "\n---\n\n## 0. 当前默认配置", 1)

# 3) 第 1 节表格里的旧命令 llm N -> 新脚本
for n in "12345":
    s = s.replace("`llm %s`" % n, "`启动大模型.bat start %s`" % n)

# 4) 兜底：其它残留的 llm N 写法
s = s.replace("E:\\llm-cpp\\llm.bat", "E:\\llm-cpp\\启动大模型.bat")

io.open(P, 'w', encoding='utf-8', newline='\r\n').write(s)
print("updated:", P)
print("残留 llm 命令:", [l.strip() for l in s.split('\n') if 'llm 1' in l or 'llm 2' in l or '`llm' in l])
