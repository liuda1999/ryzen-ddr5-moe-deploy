@echo off

REM 注意 <nul：chcp 改代码页时会读并清空输入缓冲，重定向/管道送 stdin

REM 的场景下会把第一行输入吞掉（实测），加 <nul 让它立刻读到 EOF。

REM 对交互使用同样有益：不会吃掉检查期间提前键入的内容。

chcp 936 <nul >nul 2>nul

setlocal EnableExtensions

title Qwen3.6-35B 本地大模型 一键开关



REM ============================================================

REM   启动大模型_StartModel.bat  ——  二合一开关（启动 / 关闭 / 重启 / 状态）

REM

REM   双击运行：

REM     服务未运行  ->  先做环境与硬件检查，再检查模型：

REM                       没有模型  ->  引导下载（1=IQ3_S / 2=Q4_K_M，断点续传）

REM                       已有模型  ->  跳过，直接按档位启动

REM     服务已运行  ->  默认关闭服务（也可选择重启、打开网页、看日志）

REM

REM   命令行用法：

REM     启动大模型_StartModel.bat               交互模式（自动判断启动或关闭）

REM     启动大模型_StartModel.bat start  [1-6]  启动（档位可省，默认按显存推荐）

REM     启动大模型_StartModel.bat stop          关闭

REM     启动大模型_StartModel.bat restart [1-6] 重启

REM     启动大模型_StartModel.bat status        只看状态

REM     启动大模型_StartModel.bat menu          服务在跑时打开管理菜单（重启/开网页/看日志）

REM     启动大模型_StartModel.bat check         只做环境与安全检查

REM

REM   深度思考（推理链）：

REM     默认关闭 —— 关闭后首个字更快出现、生成 token 更省。

REM     交互模式下会在选完档位后询问；也可用命令行直接指定：

REM       启动大模型_StartModel.bat start 2 think     开启深度思考（回答更严谨，但更慢）

REM       启动大模型_StartModel.bat start 2 nothink   关闭深度思考（快）

REM

REM   局域网访问：

REM     服务默认绑定 0.0.0.0，局域网其它设备可访问 http://<本机IP>:35035，

REM     但必须携带密钥（首次启动自动生成到根目录 api-key.txt）。

REM     只想本机可用时，把下面的 HOST 改回 127.0.0.1。

REM

REM   GPU 混合卸载（只针对 NVIDIA 独立显卡；核显与非 N 卡一律按纯 CPU）：

REM     默认开启（GPU_MODE=auto）。把「每 token 必读」的那部分权重放进显存，

REM     体积最大的 MoE 专家权重仍留在内存（它们每 token 只用到 8/256）。

REM     实测：卸载到显存的非专家权重仅约 1.3 GiB（40 层），占总量约 6%；

REM     32K 上下文的 KV 只占约 640 MiB（该模型为混合注意力，KV 增长很慢）。

REM     GPU 不可用时（没 N 卡 / 没后端 / 没 CUDA 运行库 / 显存太小）会自动

REM     退回纯 CPU，不会阻止启动 —— 所以默认开着是安全的，CPU 永远兜底。

REM     关闭方式（三者其一）：

REM       a) 把下面的 GPU_MODE 改成 off

REM       b) 命令行加一个 nogpu 参数        —— 启动大模型_StartModel.bat start 2 nogpu

REM       c) 想自己控层数：把 GPU_MODE 改成 manual，再填下面几个值

REM     想临时试一次：启动大模型_StartModel.bat start 2 gpu

REM     缺后端 / 缺 CUDA 运行库请跑 环境检查_EnvCheck.bat 的「GPU 支持自检」。

REM     原理与显存预算详见：参数阶梯手册_TierManual.md 的「GPU 混合卸载」章节。

REM

REM ============================================================

REM   模型自动下载（只在「没有模型」时触发）

REM     顺序：环境与硬件检查 -> 检查模型 -> 没有才下载 -> 档位选择

REM       已有模型（Q4_K_M / IQ3_S 任一存在）-> 跳过，直接选档位启动

REM       没有模型 -> 菜单选量化后自动下载：

REM         1  IQ3_S    约 12.74 GB   32 GB 内存设备首选，速度略快

REM         2  Q4_K_M   约 20.61 GB   推荐（32G 内存，最多 64K）

REM     下载用系统自带 curl：-C - 断点续传，中断后重跑会接着下；

REM     下载前检查磁盘空间，完成后校验文件大小，然后自动进入档位选择。

REM     模型来源：https://hf-mirror.com/unsloth/Qwen3.6-35B-A3B-GGUF

REM     手动下载 / 换模型：llama.cpp\models\下载模型.md

REM ============================================================



REM   可在任意位置追加 quiet 参数进入静默模式（计划任务 / 开机自启用）：

REM     启动大模型_StartModel.bat start 2 quiet

REM

REM   档位与实测数据详见：参数阶梯手册_TierManual.md

REM ============================================================



set "ROOT=%~dp0"

set "BIN_DIR=%ROOT%llama.cpp\build-zen5\bin"

set "MODEL=%ROOT%llama.cpp\models\Qwen3.6-35B-A3B-UD-Q4_K_M.gguf"

set "MMPROJ=%ROOT%llama.cpp\models\mmproj-BF16.gguf"

set "SERVER_EXE=%BIN_DIR%\llama-server.exe"

set "LOG_DIR=%ROOT%logs"

set "PID_FILE=%LOG_DIR%\server.pid"

REM 绑定地址：0.0.0.0 = 允许局域网其它设备访问（需配 --api-key-file 鉴权）

REM           127.0.0.1 = 仅本机可用（最安全，局域网连不上）

set "HOST=0.0.0.0"

set "CHECK_HOST=127.0.0.1"

set "PORT=35035"

REM 局域网访问密钥文件（首次启动自动生成；可手工加多行 key 做轮换）

set "KEY_FILE=%ROOT%api-key.txt"

set "READY_TIMEOUT=480"
REM 2026-10-22：GPU_LOADMODE=none 时启动要真读 20.6 GiB（mmap 只是映射，秒回）。
REM 模型在 page cache 里时约 7~9 s，冷盘实测 60~120 s，老硬盘更久 —— 300 s 会误判「没起来」。
REM 空闲休眠：连续无推理任务这么多秒后，llama-server 会释放模型与 KV（把内存/显存还回去），
REM 下次请求再自动重新加载（= 回收资源 + 重新预热）。默认 7200 秒 = 2 小时。
REM llama.cpp 自身默认是 -1（从不休眠）；这里显式设 2 小时：够一整天随手用，
REM 又不会常年白占 20 GB 内存。想更早回收就调小，想更久不回收就调大。
set "IDLE_SLEEP_SEC=7200"



REM ============================================================

REM  GPU 混合卸载（只针对 NVIDIA 独立显卡）

REM  默认 auto：有 N 卡就压榨显存提速，没有就自动退回纯 CPU。

REM

REM   auto   = 默认值。自动探测，按显存算出卸几层；不可用则退回纯 CPU

REM   off    = 完全不启用，传 --n-gpu-layers 0（与旧版逐字节一致）

REM   manual = 完全按下面几个值拼参数

REM ============================================================

set "GPU_MODE=auto"

REM manual 模式专用（auto 模式忽略它们）：

set "GPU_DEVICE="         REM 指定设备，如 CUDA0；留空=自动

set "GPU_LAYERS="         REM -ngl 值：数字 / auto / all

set "CPU_MOE="            REM all（全部专家留内存）或层数，如 41

set "MOE_CACHE_MIB="      REM 专家显存缓存 MiB，0/留空=不用

set "KV_OFFLOAD="         REM on / off；off = KV 留内存（省显存，适合小显存卡）

REM 性能参数（统一，不分显存档位）—— 依据 2026-10-17 在 GTX 1060 3GB 上的实测：

REM   UB = 物理批大小（-ub）。两条实测结论不同，按显存档位分开：
REM     · 3 GB 纯 CPU 路线（--cpu-moe）：512→1024 预填充 177.9 → 246.3（+38%）、
REM       再上 2048 反而掉到 222.7（-10%）。故 6 GB 及以下保持 1024。
REM     · 8 GB 及以上（MoE 被 op-offload 交给显卡）：prefill 每个 ubatch 都要把
REM       17.7 GiB 专家张量搬一遍 PCIe，ub 翻倍 = 搬运次数减半。2026-10-22 在
REM       RTX 2070 8GB / 96K / E=7 / 16 线程实测：
REM         ub 1024 → PP4K 466.8 / PP16K 396.9 / decode 46.1 / compute 660 MiB
REM         ub 1536 → PP4K 473.7 / PP16K 410.0 / decode 46.1
REM         ub 2048 → PP4K 680.5（+46%）/ PP16K 550.6（+39%）/ decode 45.5 / compute 914 MiB
REM       故 8 GB 及以上用 2048。注意：compute 缓冲从 660 涨到 914 MiB，
REM       GPU_FIXED_MIB 必须同步上调（见 :BUILD_GPU_ARGS 里的分带覆盖），否则层数会算多 → 越界分页。
set "UB=1024"

REM   FA = Flash Attention（on / off / auto）。本机实测对预填充的贡献在噪声内（175.7 vs 177.9），
REM        主要价值是省 KV 显存；现代卡可能更明显。老架构/头维度不支持导致加载失败时改成 off。
set "FA=on"

REM auto 模式的参数（MiB）—— 取值来自 2026-10-16 在 GTX 1060 3GB 上做的

REM 「层数 × 显存 × 速度」扫掠实测（32K 档、--cpu-moe、24 线程）：

REM   ngl=0  专用 1535 MB / 共享 112 MB          13.75 t/s

REM   ngl=16 专用 2397 / 共享 302                17.18

REM   ngl=24 专用 2659 / 共享 366                17.80

REM   ngl=32 专用 2612 / 共享 750                19.50

REM   ngl=40 专用 2619 / 共享 1198               20.50

REM   关键结论：专用显存被驱动封顶在 ~2620 MB（= 总量 - 其它程序 - 驱动保留），

REM   超出部分会落到 host-mapped「共享内存」里，每 token 走 PCIe。所以预算要算准，

REM   对 3GB 这种卡尤其重要 —— 算多了就有一部分权重长期走 PCIe。

set "GPU_MIN_FREE_MIB=1536"   REM 空闲显存低于此值就不启用（再低收益太小）

set "GPU_LAYER_MIB=40"        REM 每层「非专家权重」≈40 MiB（实测 39.6：41 层共 1625 MiB）

set "GPU_EXPERT_LAYER_MIB=500" REM 每层「MoE 专家权重」≈500 MiB（Q4_K_M 实测单层 432~498 MiB，取最大 498 上取整，防越界分页）

set "GPU_FIXED_MIB=600"       REM 计算缓冲 + CUDA 上下文（不含 KV）。按 UB=1024 标定：ub512 时实测约 413，ub1024 实测 +146~160 → 约 573，取 600；3~4 GB 带按实测覆盖为 620（见 GPU_BAND_SMALL）

REM 3~4 GB 专用：620 不是拍脑袋，是 2026-10-26 在 GTX 1060 3GB 上扫出来的「prefill 不塌」线。
REM 现象（64K 档，同一张卡、同一提示 12000 token、连续采样 350 ms）：
REM   32 层 → 峰值 2749，prefill 292.0 t/s，decode 23.24
REM   36 层 → 峰值 2843，prefill 209.5 t/s  ← 塌 28%
REM   38 层 → 峰值 2899，prefill 210.2 t/s
REM 32K 档 40 层（峰值 2795）仍是 296.7，不掉。可见塌的不是「层数」而是「采样峰值 > ~2760」，
REM 且只在 KV 更大的 64K 档触发：sampler 抓的是稳态，prefill 的瞬时计算缓冲还要再高 100~150，
REM 一旦顶到驱动可用上限（total 3072 - reserved 107），WDDM 就用共享内存兜底，prefill 直接腰斩。
REM 结论：这块卡的真实安全线约 2760，不是标称 3072。620 的预留刚好让 64K 稳在 32 层、
REM 32K 仍能封顶 40 层（baseline ≈ 400 时实测 40/40）。
REM 教训：把 fixed 压到 380 试过，64K 能多上 6 层但 prefill 从 292 掉到 210，净亏。

set "GPU_SAFETY_MIB=96"       REM 安全垫：留出余量，驱动就不必回收 llama 的页（调大更保险、更慢）

set "GPU_MMPROJ_MIB=1134"     REM 视觉塔 offload 到显卡时占的专用显存。2026-10-22 在 8 GB 卡上从日志读到 [mtmd] estimated worst-case memory usage of mmproj is 1134 MiB（旧值 930 是 3 GB 卡上估的，少算 204）；仅 MMPROJ_OFFLOAD=gpu 时参与预算

set "GPU_MMPROJ_MIN_GAIN=8"   REM auto 模式下：省掉视觉塔能让可用层数多出这么多层以上，就自动不载它

set "GPU_SLACK_MIN_MIB=512"   REM 算完层数后必须剩下的显存余量；不足就先让视觉塔腾地方

set "GPU_BAND_HIGH_UB=7000"   REM ≥ 它（8/12/14/16G 带）走 ub 2048 + compute 预算 900 MiB；以下保持 ub 1024 + 600（3~6G 是纯 CPU 卸专家路线，实测 ub 2048 反而慢 10%）

set "GPU_BAND_SMALL=5120"     REM ≤ 它（3~4G 带）用 620 覆盖计算缓冲预算：实测这块卡的真实安全线约 2760 MiB（标称 3072 - reserved 107 - prefill 瞬时尖峰），压到 380 会让 64K 档多上 6 层但 prefill 腰斩

set "GPU_VRAM_BAND_T2=11000"  REM 显存分带阈值（MiB）：低于它算 8G 带（8192/6144/4096/3072）

set "GPU_VRAM_BAND_T3=14000"  REM 低于它算 12G 带（12288）

set "GPU_VRAM_BAND_T3B=15000" REM 低于它算 14G 带（14336）

set "GPU_VRAM_BAND_FULL=20000" REM 低于它算 16G 带（16384）；达到或超过则保持旧行为（专家不设上限）

set "GPU_EXPERT_CAP_T1=8"     REM 专家层上限：8G 及以下放到 8 层（2026-10-22 在 RTX 2070 8GB 实测：96K 档在 512 MiB 余量底线下自动落到 7 层，decode 47.3 t/s；E=8 是 47.0，差在噪声内，但余量少 450 MiB）

set "GPU_EXPERT_CAP_T2=12"    REM 12G 带（12288）：按 8G 实测的 8 层抬 45~50% → 12 层

set "GPU_EXPERT_CAP_T3B=14"   REM 14G 带（14336）：按「每 1 GB 显存 1 层专家」线性外推 → 14 层

set "GPU_EXPERT_CAP_T3=16"    REM 16G 带（16384）：按 8G 的 8 层翻倍 → 16 层

REM 三个性能开关（2026-10-22 在 RTX 2070 8GB / 96K 上逐项实测，见参数阶梯手册）

REM   GPU_LOADMODE：auto = 默认 mmap（权重按需缺页）；none = 启动时全量读进内存。
REM     none 拿回三样东西：CUDA pinned host 内存（H2D 带宽约翻倍）、repack 内核、
REM     以及「首次生成要现场缺页」的惩罚。实测 96K/E=1：PP4K 378.6 → 423.7 t/s（+12%）、
REM     首轮 decode 30.8 → 38.6 t/s（+25%）、纯 decode 40.8 → 41.3。代价是启动多读 20.6 GiB
REM     （模型已在 page cache 里时约 7~9 s，冷盘约 60~120 s，故 READY_TIMEOUT 提到 480）。
set "GPU_LOADMODE=none"

REM   GPU_OPOFFLOAD：on = 默认（MoE 的 batch≥32 时整块交给显卡）。2026-10-22 实测过 off：
REM     prefill 阶段 CPU 从 3.3 核升到 23.9 核（看起来「满载」了），但 PP4K 从 378.6 掉到
REM     332.2 t/s —— CPU 逐块算 17.7 GiB 专家比显卡边搬边算更慢，decode 也没有收益。
REM     结论：CPU 在 prefill 时空转不是浪费，是显卡在干活；把活抢回来只会更慢。保持 on。
set "GPU_OPOFFLOAD=on"

REM   GPU_MOE_CACHE_MIB：专家 LRU 显存缓存。实测是负收益（E=2+2 GiB：decode 41.5 → 37.3；
REM     E=0+3 GiB：42.0 → 39.2），每 token 的缓存命中省下的算力抵不过 PCIe 搬权重。默认关。
set "GPU_MOE_CACHE_MIB=0"

REM 线程数取物理核数 16（9950X = 16 核 / 32 线程），全档位统一。
REM 依据（2026-10-22 实测，RTX 2070 8G / 96K / E=8，手册 C 组）：
REM   16 → 47.0、20 → 45.1、24 → 45.4、28 → 45.0、32 → 43.7 t/s。
REM   一过物理核数就掉 3~4%，原因是 SMT 兄弟共享同一套 AVX-512 执行单元，
REM   单条线程完成时间接近翻倍；而 ggml 每个矩阵乘都是 fork-join + 全局 barrier，
REM   最快的必须等最慢的，于是那 8 个「双线程核」成为短板，另外 8 个核算完只能自旋空等。
REM 此前取 24 的理由是「把 CPU 顶到 23.7 核」，但那是假象：多出的 8 核在 barrier 上
REM   忙等，速度反而低 3.5%。CPU 占用高 ≠ 有效算力。
REM 已知代价：纯 CPU 路线（3~6 GB 的 --cpu-moe）prefill 也压在 CPU 上，
REM   2026-10-26 实测 pp512：16 线程 202.1 / 24 线程 213.6 / 32 线程 216.3，
REM   即 16 线程读提示词低约 5.4%。若某台机器更看重长提示词吞吐，把这里和
REM   档位表的 THREADS 一起调回 24 即可（decode 会回落 3.5%）。
set "GPU_THREADS=16"

set "GPU_NLAYER=40"           REM 模型层数（GGUF block_count=40），用来给算出的层数封顶

REM 视觉塔开关：auto = 按显存自动取舍（省下它能多上 GPU_MMPROJ_MIN_GAIN 层以上

REM 就不载，文字优先速度）；on = 强制载入（要处理图片）；off = 强制不载。

REM 它实打实吃约 930 MiB 专用显存 —— 3 GB 卡上那是十几层权重，滑不滑得来

REM 差别很大（实测 40 层 15.6 t/s vs 21 层 11.1 t/s，深上下文解码）。

set "MMPROJ_SW=auto"

REM 视觉塔放在哪：host = 放系统内存（共享显存，不占专用显存）；gpu = 放显卡专用显存。

REM 本项目的设计是「视觉塔走共享显存」——mmproj 是 BF16 约 800 MiB，放专用显存等于

REM 白丢掉 1 到 2 层专家层的空间，而它只在处理图片时才算，放内存不影响文本速度。

REM 放到内存要用 --no-mmproj-offload（官方默认是 offload 到 GPU）。

set "MMPROJ_OFFLOAD=host"

REM 层数按「显卡总显存 - 其它程序占用 - 固定开销 - KV - 安全垫」算：

REM   KV(f16)  ≈ 上下文 ÷ 50 MiB，KV(q8_0) ≈ 上下文 ÷ 100 MiB（实测 32K 省 320 MiB）

REM   f16 算出来层数不足 32（速度拐点）时自动改用 q8_0（省一半 KV，代价 ~0.7% 速度）。

REM   相比旧版「总量 - 448」的粗算，这里把 KV、其它程序占用、视觉塔都算进去了。

REM 换模型时 GPU_LAYER_MIB 与 GPU_NLAYER 都要跟着改：

REM   GPU_NLAYER   = 模型层数（GGUF 元数据可见）

REM   GPU_LAYER_MIB = 「非专家权重」总大小 ÷ 层数（用 _维护脚本\gguf_tensor_stats.py 量）

REM ============================================================



REM quiet = 静默模式（供计划任务 / 开机自启调用：不等待按键、不打开浏览器）

set "QUIET=0"

if /i "%~1"=="quiet" set "QUIET=1"

if /i "%~2"=="quiet" set "QUIET=1"

if /i "%~3"=="quiet" set "QUIET=1"

if /i "%~4"=="quiet" set "QUIET=1"

if /i "%~5"=="quiet" set "QUIET=1"



REM 深度思考（推理链）：on = 开启，off = 关闭。关闭后响应更快、更省 token。

REM 默认关闭；命令行出现 think / nothink 时以此为准，不再在菜单里询问。

set "THINK=off"

set "THINK_FIXED="

if /i "%~1"=="think"   set "THINK=on"

if /i "%~2"=="think"   set "THINK=on"

if /i "%~3"=="think"   set "THINK=on"

if /i "%~4"=="think"   set "THINK=on"

if /i "%~1"=="nothink" set "THINK=off"

if /i "%~2"=="nothink" set "THINK=off"

if /i "%~3"=="nothink" set "THINK=off"

if /i "%~4"=="nothink" set "THINK=off"

if /i "%~1"=="think"   set "THINK_FIXED=1"

if /i "%~2"=="think"   set "THINK_FIXED=1"

if /i "%~3"=="think"   set "THINK_FIXED=1"

if /i "%~4"=="think"   set "THINK_FIXED=1"

if /i "%~1"=="nothink" set "THINK_FIXED=1"

if /i "%~2"=="nothink" set "THINK_FIXED=1"

if /i "%~3"=="nothink" set "THINK_FIXED=1"

if /i "%~4"=="nothink" set "THINK_FIXED=1"



REM GPU 开关：默认就是 auto（有 N 卡就启用），这里只处理命令行的临时覆盖：

REM   nogpu -> 本次强制纯 CPU      gpu -> 本次强制启用

REM 命令行优先级最高，不改文件，重启后回到文件里的设置。

if /i "%~1"=="gpu"   goto :GPUCLI_ON

if /i "%~2"=="gpu"   goto :GPUCLI_ON

if /i "%~3"=="gpu"   goto :GPUCLI_ON

if /i "%~4"=="gpu"   goto :GPUCLI_ON

if /i "%~5"=="gpu"   goto :GPUCLI_ON

if /i "%~1"=="nogpu" set "GPU_MODE=off"

if /i "%~2"=="nogpu" set "GPU_MODE=off"

if /i "%~3"=="nogpu" set "GPU_MODE=off"

if /i "%~4"=="nogpu" set "GPU_MODE=off"

if /i "%~5"=="nogpu" set "GPU_MODE=off"

goto :GPUCLI_END

:GPUCLI_ON

set "GPU_MODE=auto"

:GPUCLI_END



if not exist "%LOG_DIR%" mkdir "%LOG_DIR%" >nul 2>nul



REM ---------------- 参数模式 ----------------

if /i "%~1"=="status"  goto :STATUS_ONLY

if /i "%~1"=="check"   goto :ENV_CHECK_ONLY

if /i "%~1"=="start"   goto :ARG_START

if /i "%~1"=="stop"    goto :ARG_STOP

if /i "%~1"=="restart" goto :ARG_RESTART

REM menu：服务在跑时想用「重启/开网页/看日志」菜单（无参数时是严格开关，直接关闭）

if /i "%~1"=="menu"    goto :MENU_RUNNING

if "%~1"==""           goto :MAIN

echo [错误/ERROR] 未知参数：%~1 / unknown argument: %~1

echo.

echo 用法/USAGE：启动大模型_StartModel.bat [start^|stop^|restart^|status^|check^|menu] [档位/tier 1-7]

echo.

call :PAUSE_IF

exit /b 1



REM ============================================================

:MAIN

REM 二合一开关（无参数时的行为）：

REM   服务没在跑 → 走启动流程（环境检查 → 档位 → 启动）

REM   服务正在跑 → 直接关闭，不弹菜单（这就是「再双击一次 = 关掉」）

REM   想看「重启 / 打开网页 / 查看日志」菜单：启动大模型_StartModel.bat menu

call :DETECT

if defined SRV_PID goto :TOGGLE_STOP

goto :MENU_STOPPED



REM ============================================================

:TOGGLE_STOP

REM 严格开关：这里必须「直接关」。加菜单会让双击两次的直觉失效。

echo.

echo [开关/TOGGLE] 检测到服务正在运行，直接关闭。/ service is running, stopping it now.

echo                需要「重启 / 打开网页 / 查看日志」菜单请运行 / for the menu run:

echo                    启动大模型_StartModel.bat menu

goto :DO_STOP



REM ============================================================

:ARG_START

if not "%~2"=="" set "TIER=%~2"

if not defined TIER (

  call :TIER_HINT

  if defined REC_TIER ( set "TIER=%REC_TIER%" ) else ( set "TIER=1" )

)

call :DETECT

if defined SRV_PID (

  echo [提示/HINT] 服务已在运行（PID %SRV_PID%），无需重复启动。/ service already running, no need to start again

  echo        再次运行本脚本即可关闭，或用/Run this script again to stop, or: 启动大模型_StartModel.bat restart

  exit /b 0

)

goto :DO_START



:ARG_STOP

call :DETECT

if not defined SRV_PID (

  echo [提示/HINT] 服务未在运行，无需关闭。/ service is not running, nothing to stop

  if exist "%PID_FILE%" (

    echo [清理/CLEAN] 删除残留的状态文件。/ removing stale state file

    del "%PID_FILE%" >nul 2>nul

  )

  exit /b 0

)

goto :DO_STOP



:ARG_RESTART

if not "%~2"=="" set "TIER=%~2"

call :DETECT

if not defined SRV_PID goto :DO_START

goto :DO_RESTART



:STATUS_ONLY

call :DETECT

if not defined SRV_PID goto :STATUS_DOWN

call :LOAD_PIDFILE

call :GET_LAN_IP

call :LOAD_KEY

echo.

echo ============================================================

echo   状态/STATUS：服务正在运行 / service is running

echo ============================================================

echo   进程/PID       %SRV_PID%

for /f "usebackq delims=" %%a in (`powershell -NoProfile -Command "[math]::Round((Get-Process -Id %SRV_PID%).WorkingSet64/1GB,1)"`) do set "SRV_MEM=%%a"

echo   内存占用/MEM   %SRV_MEM% GB

echo   配置档位/TIER   %CUR_TIER_NAME% （上下文/ctx %CUR_CTX% / 输出建议 max_tokens %CUR_OUT% / 线程/threads %CUR_T%）

call :SHOW_CUR_THINK

echo   启动时间/SINCE  %CUR_TIME%

set "GPU_REQ=%CUR_GPU%"

set "GPU_ARGS=%CUR_GPU_ARGS%"

set "GPU_LOG_STAMP=%CUR_TIME%"

call :SHOW_GPU_ACTUAL

call :SHOW_ADDR

echo ============================================================

echo.

exit /b 0



REM ============================================================

REM  子程序：显示访问地址（局域网 + 本机 + 密钥）

REM ============================================================

:SHOW_ADDR

if defined LAN_IP (

  echo   局域网地址/LAN  http://%LAN_IP%:%PORT%      ^(其它设备用这个^) / ^(use this from other devices^)

) else (

  echo   局域网地址/LAN  ^(未检测到局域网 IPv4^) / ^(no LAN IPv4 detected^)

)

echo   本机地址/LOCAL  http://127.0.0.1:%PORT%

echo   API 地址/URL    http://127.0.0.1:%PORT%/v1/chat/completions

if defined API_KEY (

  echo   访问密钥/APIKEY %API_KEY%

  echo   调用方式/USE    请求头加 Authorization: Bearer 上面这串密钥 / send header: Authorization: Bearer ^<key above^>

) else (

  echo   访问密钥/APIKEY ^(未找到 %KEY_FILE%，局域网将无法通过鉴权^) / ^(key file missing, LAN calls will be rejected^)

)

echo   输出建议/MAX_OUT  %CUR_OUT%（上下文 %CUR_CTX% 的建议 max_tokens / suggested max_tokens）

exit /b 0



:STATUS_DOWN

echo.

echo   状态/STATUS：服务未运行（端口/port %PORT% 空闲/free） / service is not running

echo   运行/RUN 启动大模型_StartModel.bat 即可启动。/ run 启动大模型_StartModel.bat to start

echo.

exit /b 0



:ENV_CHECK_ONLY

REM 先解析实际存在的模型文件（Q4_K_M 优先，IQ3_S 兜底），避免误报缺失

call :MODEL_DETECT

call :SAFETY_CHECK

echo.

if "%CHK_FAIL%"=="1" (

  echo   结论/RESULT：检查未通过，请先修复上面标记为 [失败] 的项目。/ checks failed, fix the [失败/FAIL] items above

  call :PAUSE_IF

  exit /b 1

) else (

  echo   结论/RESULT：检查全部通过，可以启动。/ all checks passed, ready to start

  call :PAUSE_IF

  exit /b 0

)



REM ============================================================

REM  服务已运行：默认动作是关闭

REM ============================================================

:MENU_RUNNING

call :LOAD_PIDFILE

call :GET_LAN_IP

call :LOAD_KEY

for /f "usebackq delims=" %%a in (`powershell -NoProfile -Command "[math]::Round((Get-Process -Id %SRV_PID%).WorkingSet64/1GB,1)"`) do set "SRV_MEM=%%a"

cls

echo ============================================================

echo   Qwen3.6-35B 本地大模型/Local LLM · 服务正在运行 / service running

echo ============================================================

echo.

echo   进程/PID       %SRV_PID%

echo   内存占用/MEM   %SRV_MEM% GB

echo   配置档位/TIER   %CUR_TIER_NAME% （上下文/ctx %CUR_CTX% / 输出建议 max_tokens %CUR_OUT% / 线程/threads %CUR_T%）

call :SHOW_CUR_THINK

echo   启动时间/SINCE  %CUR_TIME%

set "GPU_REQ=%CUR_GPU%"

set "GPU_ARGS=%CUR_GPU_ARGS%"

set "GPU_LOG_STAMP=%CUR_TIME%"

call :SHOW_GPU_ACTUAL

call :SHOW_ADDR

echo.

echo ------------------------------------------------------------

echo   1   关闭服务 / Stop service                [默认/DEFAULT]

echo   2   重启服务 / Restart ^(can change tier^)

echo   3   打开网页控制台 / Open web console

echo   4   查看最近日志 / View recent log

echo   0   退出，保持服务运行 / Exit, leave service running

echo ------------------------------------------------------------

echo.

set "ACT="

set /p "ACT=  请输入编号/Enter number [1] : "

if "%ACT%"=="" set "ACT=1"

if "%ACT%"=="1" goto :DO_STOP

if "%ACT%"=="2" goto :DO_RESTART

if "%ACT%"=="3" goto :OPEN_WEB

if "%ACT%"=="4" goto :SHOW_LOG

if "%ACT%"=="0" exit /b 0

goto :MENU_RUNNING



REM ============================================================

REM  服务未运行：默认动作是启动

REM  流程：环境与硬件检查 -> 模型检查（没有就引导下载）-> 档位菜单

REM ============================================================

:MENU_STOPPED
REM 轮次上限：内存不足会把人弹回这个菜单，如果输入来源枯竭（重定向/管道到文件尾），
REM set /p 会一直取默认值 → 反复回到同一个档位 → 死循环。和下载菜单的 MG_ROUND
REM 一样封顶，保证任何输入情况下脚本都会结束而不是刷屏。
set /a TIER_ROUND+=1
if %TIER_ROUND% GEQ 12 goto :MENU_GIVEUP

cls

REM 第一步：环境与硬件检查（首次进入时做；从「内存不足」返回时不重复）

if not defined ENV_DONE (

  call :MODEL_DETECT

  REM 模型缺失这一步只警告不拦截 —— 紧接着 MODEL_GATE 就会引导下载

  set "MODEL_SOFT=1"

  call :SAFETY_CHECK

  set "MODEL_SOFT="

  set "ENV_DONE=1"

  if "%CHK_FAIL%"=="1" (

    echo.

    echo   结论/RESULT：检查未通过，请先修复上面标记为 [失败] 的项目。/ checks failed, fix the [失败/FAIL] items above

    echo.

    call :PAUSE_IF

    exit /b 1

  )

)

REM 第二步：检查模型；没有就进下载菜单（1=IQ3_S / 2=Q4_K_M），下完自动回到这里

call :MODEL_GATE

if defined MODEL_GATE_ABORT exit /b 1

cls

call :TIER_HINT

echo ============================================================

echo   Qwen3.6-35B 本地大模型 / Local LLM
echo   服务未运行 / service stopped
echo   模型/MODEL    %MODEL_LABEL%
echo   后端/BACKEND  纯 CPU / CPU-only（AVX-512+VNNI+VBMI）
echo                 有 N 卡时自动启用显存混合卸载 / GPU offload auto with NVIDIA
if defined REC_CTX_HINT echo   显卡/GPU      检测到 %VRH% MiB 显存 / detected
if defined REC_CTX_HINT echo                 建议档位 %REC_TIER% %REC_TIER_NAME%（%REC_CTX_HINT%） / recommended
echo.
echo ------------------------------------------------------------
echo   请选择配置档位 / Choose a tier
echo ------------------------------------------------------------
echo   档位/TIER              上下文/CTX  输出建议/max  IQ3_S 内存  Q4 内存
echo   1  短任务档/Short task      32K       8192      16G        24G
echo   2  中档/Medium             48K      12288      16G        24G
echo   3  标准档/Standard         64K      16384      16G        24G
echo   4  长文档档/Long doc        96K      24576      17G        25G
echo   5  超长档/Extended        128K      32768      17G        25G
echo   6  长上下文档/Big ctx      160K      40960      18G        26G
echo   7  极限档/Maximum         192K      49152      18G        26G
echo   0  退出 / Exit
echo ------------------------------------------------------------
echo   说明 / NOTE
echo   配置/SETUP     32K 是最低档（短任务 / 无 N 卡兜底）；内存定上限、显存定速度
echo                  16G 内存 + 4G 以上显存 → IQ3_S，可到 64K
echo                  32G 内存（16G*2 双通道）→ Q4_K_M，可到 64K
echo                  64G 内存 → Q4_K_M 及以上，96K~192K 看显存
echo                  推荐/recommended：8G→96K  12G/14G→128K  16G 及以上→192K
echo   速度/SPEED     短对话约 21~24 t/s，填满后随长度缓降 / short chat ~21-24 t/s, drops as ctx fills
echo                  约每多填 1 千 token 慢 0.7 ms；30K 约 15 t/s，64K 填满约 11 t/s
echo   线程/THREAD    全部档位均为 16 线程（物理核）/ 16 threads (physical cores) for every tier
echo   空闲/IDLE      无任务 2 小时后释放内存，下次对话自动重载 / frees RAM after 2h idle, reloads on next request
echo   手册/MANUAL    详见/see 参数阶梯手册_TierManual.md
echo.

echo.

echo.

set "TIER="

set "TIER_DEF=1"

if defined REC_TIER set "TIER_DEF=%REC_TIER%"

set /p "TIER=  请输入档位编号/Enter tier [%TIER_DEF%] : "

if "%TIER%"=="" set "TIER=%TIER_DEF%"

if "%TIER%"=="0" exit /b 0

if defined THINK_FIXED goto :DO_START

goto :STEP_THINK



REM ============================================================

REM  第二步：询问是否开启深度思考

REM ============================================================

:STEP_THINK

call :APPLY_TIER

if not defined CTX goto :DO_START

cls

echo ============================================================

echo   是否开启深度思考（推理链）？/ Enable deep thinking ^(reasoning chain^)?

echo ============================================================

echo   已选档位/TIER：%TIER_NAME%      %CTX% 上下文/ctx / 输出建议 max_tokens %OUT% / %THREADS% 线程/threads（上 GPU 时改用 %GPU_THREADS% 线程，见启动横幅）

echo.

echo ------------------------------------------------------------

echo   Y   开启/ON  —— 先推理再作答，逻辑题、数学题、复杂分析更稳妥 / think first, better on logic/math/complex analysis

echo              代价/COST：先输出一段思考内容，首个字更慢、更费 token / slower first token, more tokens

echo.

echo   N   关闭/OFF —— 直接作答，响应更快、token 更省 / answer directly, faster and fewer tokens     [默认/DEFAULT]

echo              适合/GOOD FOR：日常问答、翻译、摘要、改写润色 / Q^&A, translation, summarising, rewriting

echo ------------------------------------------------------------

echo   提示/HINT：两种模式可随时切换，只要重新启动一次服务即可。/ switch anytime by restarting the service

echo.

set "TK="

set /p "TK=  开启深度思考吗？/ Enable deep thinking? (y/N) : "

if /i "%TK%"=="y" goto :TK_ON

set "THINK=off"

goto :DO_START

:TK_ON

set "THINK=on"

goto :DO_START



REM ============================================================

:DO_START

call :APPLY_TIER

if not defined CTX (

  echo [错误/ERROR] 无效档位/invalid tier：%TIER%

  call :PAUSE_IF

  goto :MENU_STOPPED

)

REM 模型门：没有模型先引导下载（命令行 start / restart 直达时也会走到）

call :MODEL_GATE

if defined MODEL_GATE_ABORT exit /b 1

REM 环境检查在档位菜单里已做过（ENV_DONE）就不再重复；

REM 命令行直达的路径没做过，在这里补做。

if defined ENV_DONE goto :DS_AFTER_ENV

cls

echo ============================================================

echo   启动前安全与环境检查 / Pre-flight safety and environment check

echo ============================================================



echo.

call :SAFETY_CHECK

if "%CHK_FAIL%"=="1" (

  echo.

  echo   检查未通过，已阻止启动 / checks failed, startup blocked（避免启动到一半崩溃或把系统拖到卡死）/ to avoid a half-broken start

  echo.

  call :PAUSE_IF

  exit /b 1

)

:DS_AFTER_ENV

cls

echo ============================================================

echo   启动前检查 / Pre-flight check：内存与显卡 / memory and GPU

echo ============================================================

call :MEM_CHECK

if "%MEM_BLOCK%"=="1" goto :MEM_NOT_ENOUGH

if "%MEM_WARN%"=="1" (

  echo.

  echo   [警告/WARN] 可用内存偏紧，继续启动可能导致系统明显卡顿甚至被系统杀掉进程。/ free RAM is tight, continuing may slow the system or get the process killed.

  REM 询问必须走子程序：写在 if 块里的话，块内 set /p 虽能读到输入，

  REM 但同一块后面的 %YN% 在整块解析时就已展开成旧值（空），

  REM 结果永远是「已取消」，用户输 y 也无法继续。

  call :ASK_MEM_CONTINUE

  if "%ASK_RC%"=="0" (

    echo   已取消，返回档位菜单。/ cancelled, back to tier menu.

    ping -n 2 127.0.0.1 >nul

    goto :MENU_STOPPED

  )

)



REM GPU 探测与参数组装：不可用时会自动退回纯 CPU，不阻断启动

call :GPU_PROBE

call :BUILD_GPU_ARGS
REM 启动前最后一次交互询问：是否轮换访问密钥（默认沿用）
call :ASK_KEY



echo.

echo ============================================================

echo   正在启动/STARTING：%TIER_NAME%

echo   上下文/ctx %CTX%   线程/threads %THREADS%   端口/port %PORT%

call :SHOW_THINK

call :SHOW_GPU_PLAN

echo ============================================================

echo.



set "TT=%time: =0%"

set "STAMP=%date:~0,4%%date:~5,2%%date:~8,2%-%TT:~0,2%%TT:~3,2%"

set "LOG_FILE=%LOG_DIR%\server-%STAMP%.log"



REM 只保留最近 10 份日志，避免长期堆积

for /f "skip=10 delims=" %%a in ('dir /b /o-d "%LOG_DIR%\server-*.log" 2^>nul') do del "%LOG_DIR%\%%a" >nul 2>nul



call :LOAD_KEY

if not defined API_KEY (

  echo [错误/ERROR] 没有可用的访问密钥，已阻止启动。/ no usable API key, startup blocked.

  echo        请检查/check %KEY_FILE% 是否存在且至少有一行非注释内容 / exists with at least one non-comment line.

  exit /b 1

)



REM ------------------------------------------------------------

REM  在后台"无窗口"启动服务（任务栏也不出现窗口）。

REM

REM  做法：用 WScript.Shell 的 Run 方法，窗口风格传 0（隐藏窗口），

REM        第 3 个参数传 $false（不等待），于是服务在一个完全独立的

REM        隐藏进程里跑起来 —— 关掉本脚本窗口不会影响服务。

REM        日志重定向交给 cmd 完成。

REM

REM  三个必须注意的细节（都踩过）：

REM    1. 整条命令只用单引号 + [char]34 拼引号，命令里不出现双引号，

REM       这样不会被 cmd 的引号规则搅乱；

REM    2. cmd /c 后面的命令以引号开头时，必须在最外面再包一对引号

REM       （就是下面 $q + $q 那里），否则 cmd 会把引号剥掉、命令报错；

REM    3. 保留 < nul：避免服务持有本窗口的输入句柄导致脚本卡住。

REM

REM  视觉塔参数（MMPROJ_PS）在 cmd 侧拼好再注入：这样关掉 mmproj 时

REM  整段消失，也不会把双引号带进 PowerShell 命令（见上面第 1 条）。

REM ------------------------------------------------------------

set "MMPROJ_PS="

if exist "%MMPROJ%" set "MMPROJ_PS=' --mmproj ' + $q + '%MMPROJ%' + $q +"

if /i "%MMPROJ_SW%"=="off" set "MMPROJ_PS="

REM auto 模式判定「视觉塔不划算」时也要真的不传 --mmproj（见 :BUILD_GPU_ARGS）

if "%BGA_MMPROJ_AUTOOFF%"=="1" set "MMPROJ_PS="

REM 视觉塔改放系统内存（共享显存）：官方默认 offload 到 GPU，这里显式关掉。

REM 只在真的会传 --mmproj 时才加这个参数，省得日志里出现无用参数。

set "MMPROJ_OFF_PS="

if defined MMPROJ_PS if /i "%MMPROJ_OFFLOAD%"=="host" set "MMPROJ_OFF_PS=' --no-mmproj-offload' +"

powershell -NoProfile -Command "$q=[char]34; $c='cmd /c ' + $q + $q + '%SERVER_EXE%' + $q + ' --model ' + $q + '%MODEL%' + $q + %MMPROJ_PS% %MMPROJ_OFF_PS% ' --host %HOST% --port %PORT% --api-key %API_KEY% --reasoning %THINK% --ctx-size %CTX% --threads %THREADS% --threads-batch %THREADS% --sleep-idle-seconds %IDLE_SLEEP_SEC% -ub %UB% -fa %FA% %GPU_ARGS% < nul > ' + $q + '%LOG_FILE%' + $q + ' 2>&1' + $q; (New-Object -ComObject WScript.Shell).Run($c, 0, $false)"



echo [信息/INFO] 正在加载/Loading %MODEL_GB% GB 模型到内存，请稍候 / usually 30~90 s ...

echo [信息/INFO] 日志/LOG：%LOG_FILE%

echo.



REM 等待进程出现，取得 PID

set "SRV_PID="

set /a GOT=0

:WAIT_PID

ping -n 2 127.0.0.1 >nul

for /f "usebackq delims=" %%a in (`powershell -NoProfile -Command "$p=@(Get-Process -Name llama-server -ErrorAction SilentlyContinue); if($p.Count -gt 0){$p[0].Id}"`) do set "SRV_PID=%%a"

if defined SRV_PID goto :GOT_PID

set /a GOT+=1

if %GOT% GEQ 20 (

  echo [错误/ERROR] 进程启动失败或已退出，请查看日志 / process failed to start, check the log：

  echo        %LOG_FILE%

  if exist "%LOG_FILE%" powershell -NoProfile -Command "Get-Content -LiteralPath '%LOG_FILE%' -Tail 25"

  call :PAUSE_IF

  exit /b 1

)

goto :WAIT_PID



:GOT_PID

echo [信息/INFO] 进程已启动/process started，PID = %SRV_PID%

echo [信息/INFO] 等待服务就绪/waiting for ready（最长/max %READY_TIMEOUT% 秒/s）...

set /a SEC=0

set /a SEC=0

set /a TICK=0

:WAIT_READY

ping -n 6 127.0.0.1 >nul

set /a SEC+=5

call :HEALTH_OK

if "%READY%"=="1" goto :READY_OK

if %SEC% GEQ %READY_TIMEOUT% goto :READY_TIMEOUT

set /a TICK+=1

if %TICK% LSS 3 goto :WAIT_READY

set "TICK=0"

echo        ... 已等待/waited %SEC% 秒/s（模型加载中/loading model）

goto :WAIT_READY



REM ============================================================

REM  子程序：就绪判定

REM  端口开始监听并不代表模型已加载完（此时 /health 返回 503

REM  "Loading model"），必须等到 /health 返回 200 才能算真正可用。

REM ============================================================

:HEALTH_OK

set "READY=0"

set "HTTPCODE="

if not exist "%SystemRoot%\System32\curl.exe" goto :HEALTH_BY_PORT

REM 注意：for /f 反引号内的命令不能以引号开头，否则 cmd 会把整串当成一个文件名

for /f "usebackq delims=" %%a in (`%SystemRoot%\System32\curl.exe -s -o nul -w "%%{http_code}" -m 5 http://%CHECK_HOST%:%PORT%/health`) do set "HTTPCODE=%%a"

if "%HTTPCODE%"=="200" set "READY=1"

exit /b 0



:HEALTH_BY_PORT

call :PORT_BUSY

if "%PORT_STATE%"=="busy" set "READY=1"

exit /b 0



:READY_TIMEOUT

echo.

echo [错误/ERROR] 等待超时/timeout，服务未能在 %READY_TIMEOUT% 秒内就绪 / not ready in time.

echo       请查看日志排查/check the log：%LOG_FILE%

if exist "%LOG_FILE%" powershell -NoProfile -Command "Get-Content -LiteralPath '%LOG_FILE%' -Tail 25"

call :PAUSE_IF

exit /b 1



:READY_OK

call :GET_LAN_IP

call :LOAD_KEY

>"%PID_FILE%" echo %SRV_PID%^|%TIER%^|%CTX%^|%THREADS%^|%STAMP%^|%THINK%^|%GPU_MODE%^|%GPU_ARGS%

echo.

echo ============================================================

echo   启动成功/STARTED，服务已就绪 / service is ready

echo ============================================================

echo   档位/TIER      %TIER_NAME%（上下文/ctx %CTX% / 输出建议 max_tokens %OUT% / 线程/threads %THREADS%）

call :SHOW_THINK

set "GPU_REQ=%GPU_MODE%"

set "GPU_LOG_STAMP=%STAMP%"

call :SHOW_GPU_ACTUAL

echo   进程/PID       %SRV_PID%

echo   日志/LOG       %LOG_FILE%

echo.

call :SHOW_API_BLOCK

echo.

if "%QUIET%"=="1" exit /b 0



set "YN="

REM 启动成功即预热：不要等用户第一次提问才开始读权重
call :WARMUP
set /p "YN=  是否打开网页控制台？/ Open web console? (Y/n) : "

if /i "%YN%"=="n" goto :START_DONE

start "" http://%HOST%:%PORT%

:START_DONE

echo.

echo   提示/HINT：再次运行本脚本即可关闭服务 / run this script again to stop it（会释放内存/frees RAM）.

echo.

call :PAUSE_IF

exit /b 0



REM ============================================================

REM  子程序：显示思考模式（当前启动参数）

REM ============================================================

:WARMUP
REM 预热：启动后立刻发一个真实的小请求，让 llama.cpp 把权重读进内存/显存、
REM       提示词特意选成「必然要生成几十个 token」的那种：MoE 每 token 激活 8/256 个专家，
REM       生成得越多，被真正读进来的专家就越全（约 64 token 能覆盖绝大多数），
REM       冷缓存（刚开机）时收益最明显。
REM       建好 CUDA 图与 KV 结构，用户第一次对话就不用再等首字延迟。
REM 任何一步失败都只提示、不阻断 —— 最坏情况只是回到「首次对话稍慢」。
set "WARM_RC=0"
set "WARM_KEY="
REM 密钥文件可能有多把（展示时用逗号拼过），请求头只带第一把
for /f "tokens=1 delims=," %%a in ("%API_KEY%") do set "WARM_KEY=%%a"
if not defined WARM_KEY exit /b 0
if not exist "%SystemRoot%\System32\curl.exe" goto :WARM_NOCURL
set "WARM_JSON=%TEMP%\llm-warmup.json"
> "%WARM_JSON%" echo {"messages":[{"role":"user","content":"Count from 1 to 60, numbers only, separated by spaces."}],"max_tokens":96,"temperature":0,"stream":false}
if not exist "%WARM_JSON%" exit /b 0
echo   预热/WARMUP   正在预热模型，预热后首次对话免等待 / warming up for a fast first reply ...
"%SystemRoot%\System32\curl.exe" -s -f -o nul -m 600 -H "Content-Type: application/json" -H "Authorization: Bearer %WARM_KEY%" --data-binary "@%WARM_JSON%" http://%CHECK_HOST%:%PORT%/v1/chat/completions
set "WARM_RC=%errorlevel%"
del "%WARM_JSON%" >nul 2>nul
if not "%WARM_RC%"=="0" goto :WARM_FAIL
echo   预热/WARMUP   完成/done，首次对话已就绪 / first reply is ready now
exit /b 0
:WARM_NOCURL
echo   [提示/HINT] 未找到 curl，跳过预热 / curl not found, warmup skipped（首次对话会稍慢 / first reply may be slower）
exit /b 0
:WARM_FAIL
echo   [提示/HINT] 预热未成功/warmup failed（不影响使用/harmless），首次对话会稍慢 / first reply may be slower
exit /b 0


:SHOW_THINK

if /i "%THINK%"=="on" echo   深度思考 开启  ^(先推理再作答：更严谨，但更慢、更费 token^)

if /i not "%THINK%"=="on" echo   深度思考 关闭  ^(直接作答：更快、token 更省^)

exit /b 0



REM ============================================================

REM  子程序：显示思考模式（读自启动记录，供 status / 运行中菜单用）

REM ============================================================

:SHOW_CUR_THINK

if /i "%CUR_THINK%"=="on" echo   深度思考   开启

if /i not "%CUR_THINK%"=="on" echo   深度思考   关闭

exit /b 0



REM ============================================================

REM  子程序：显示本次服务的 API 信息，并把密钥复制到剪贴板

REM ============================================================

:SHOW_API_BLOCK

echo ============================================================

echo       ★  服务地址与密钥  /  ENDPOINT + KEY

echo ============================================================

if defined LAN_IP echo       局域网/LAN     http://%LAN_IP%:%PORT%/v1

if not defined LAN_IP echo       局域网/LAN     （未检测到局域网 IPv4）

echo       本机  /LOCAL   http://127.0.0.1:%PORT%/v1

echo       密钥  /KEY     %API_KEY%

echo ============================================================

echo   客户端填法/CLIENT   Base URL=上面地址  API Key=上面密钥  Model 留空

echo   输出/max_tokens     %OUT%（本档位 ctx %CTX% 的建议值 / suggested for this tier）

echo   注意/NOTE           密钥区分大小写、勿加 sk- 前缀；只认 Authorization 请求头

echo.

echo   curl 示例：

echo     curl -H "Authorization: Bearer %API_KEY%" \

echo          http://127.0.0.1:%PORT%/v1/chat/completions \

echo          -H "Content-Type: application/json" \

echo          -d "{\"messages\":[{\"role\":\"user\",\"content\":\"hi\"}]}"

echo ============================================================

call :COPY_KEY

exit /b 0



:COPY_KEY

if not defined API_KEY exit /b 0

<nul set /p "=%API_KEY%"| clip >nul 2>nul

if errorlevel 1 exit /b 0

echo   密钥已复制到剪贴板 / key copied to clipboard，可直接粘贴到客户端 / paste it into your client.

exit /b 0



REM ============================================================

REM  内存不足：给出三条出路 + 各档位可行性，然后回档位菜单重选

REM ============================================================

:MENU_GIVEUP
REM 正常交互几乎不会走到这里（要连续 12 次回到档位菜单）；走到就明确退出，
REM 而不是继续刷屏。
echo.
echo   [提示/HINT] 反复回到档位菜单多次（输入可能已耗尽）/ too many returns to the tier menu;
echo         脚本退出，避免空转 / exiting to avoid spinning。可重新运行本脚本再试 / run again to retry.
echo.
exit /b 1

:MEM_NOT_ENOUGH

echo.

echo ============================================================

echo   内存不足，已阻止启动 / Not enough RAM, startup blocked

echo ============================================================

echo   本档位/tier %TIER_NAME%（%CTX% 上下文/ctx）+ 模型 "%MODEL_LABEL%"
echo   需要约/needs ~%NEED_GB% GB 总内存/total RAM；本机总内存/total %TOTAL_GB% GB，可用/free %FREE_GB% GB。

REM 上一条已给出 total 与 free，这里不重复

echo.

call :SHOW_TIER_FIT

echo.

echo   三个解决办法，任选其一 / three options, pick one：

echo     1  关闭其它占内存的程序后重试 / close other memory-hungry apps and retry（浏览器/browser、虚拟机/VM、其它模型服务）

echo     2  在下面标注为「可用」的档位里挑一个更小的 / pick a smaller tier marked 可用/OK below

echo     3  换更小的模型 / use a smaller model：IQ3_S 只有 12.7 GB
echo        把 Qwen3.6-35B-A3B-UD-IQ3_S.gguf 放进 models 目录即可，脚本会自动改用它 /
echo        drop IQ3_S into the models folder and the script picks it up automatically

REM 已并入上一条

echo.

if "%QUIET%"=="1" exit /b 1

echo   按回车返回档位菜单重新选择 / press Enter to go back to the tier menu.

echo.

call :PAUSE_IF

goto :MENU_STOPPED



REM ============================================================

:DO_RESTART

REM 未指定档位时，沿用上次启动记录中的档位（读不到则按显存推荐，再回落到 16K）

if not defined TIER (

  call :LOAD_PIDFILE

  if defined CUR_TIER set "TIER=%CUR_TIER%"

)

if not defined TIER (

  call :TIER_HINT

  if defined REC_TIER ( set "TIER=%REC_TIER%" ) else ( set "TIER=1" )

)

echo.

echo [信息/INFO] 正在重启服务/Restarting service...

call :DO_STOP

ping -n 4 127.0.0.1 >nul

goto :DO_START



REM ============================================================

:DO_STOP

echo.

echo ============================================================

echo   正在关闭服务/Stopping service（PID %SRV_PID%）

echo ============================================================

for /f "usebackq delims=" %%a in (`powershell -NoProfile -Command "[math]::Round((Get-Process -Id %SRV_PID% -ErrorAction SilentlyContinue).WorkingSet64/1GB,1)"`) do set "SRV_MEM=%%a"

echo [信息/INFO] 当前占用内存/memory in use：%SRV_MEM% GB，正在释放/releasing...

taskkill /PID %SRV_PID% >nul 2>nul

set /a WAIT=0

:STOP_WAIT

ping -n 3 127.0.0.1 >nul

set /a WAIT+=2

call :DETECT

if not defined SRV_PID goto :STOP_OK

if %WAIT% GEQ 6 goto :STOP_FORCE

goto :STOP_WAIT

:STOP_FORCE

echo [警告/WARN] 优雅退出超时，改为强制结束进程 / graceful exit timed out, killing process...

taskkill /F /PID %SRV_PID% >nul 2>nul

ping -n 4 127.0.0.1 >nul

call :DETECT

if defined SRV_PID (

  echo [错误/ERROR] 进程 %SRV_PID% 无法结束，请手动在任务管理器中关闭 / cannot kill it, close it manually in Task Manager.

  call :PAUSE_IF

  exit /b 1

)

:STOP_OK

if exist "%PID_FILE%" del "%PID_FILE%" >nul 2>nul

set /a SEC=0

:STOP_PORT_WAIT

ping -n 3 127.0.0.1 >nul

set /a SEC+=2

call :PORT_BUSY

if "%PORT_STATE%"=="free" goto :STOP_PORT_OK

if %SEC% GEQ 20 (

  echo [警告/WARN] 进程已结束，但端口 %PORT% 仍未释放 / process gone but port not yet released（系统回收需要一点时间 / OS needs a moment）.

  goto :STOP_DONE

)

goto :STOP_PORT_WAIT

:STOP_PORT_OK

echo [完成/DONE] 端口/port %PORT% 已释放/released.

:STOP_DONE

echo.

echo   服务已关闭，内存已释放 / Service stopped, memory released.

echo.

call :PAUSE_IF

exit /b 0



REM ============================================================

:OPEN_WEB

echo.

echo [信息/INFO] 正在打开/Opening http://%HOST%:%PORT% ...

start "" http://%HOST%:%PORT%

echo [完成/DONE] 服务保持运行 / Service left running.

echo.

call :PAUSE_IF

exit /b 0



:SHOW_LOG

echo.

set "LASTLOG="

for /f "delims=" %%a in ('dir /b /o-d "%LOG_DIR%\server-*.log" 2^>nul') do (

  set "LASTLOG=%%a"

  goto :SHOWLOG_GOT

)

:SHOWLOG_GOT

echo ---------------- 最近 30 行日志 / Last 30 log lines ----------------

if not defined LASTLOG (

  echo   暂无日志文件 / no log file yet

) else (

  echo   文件/File：%LASTLOG%

  echo.

  powershell -NoProfile -Command "Get-Content -LiteralPath '%LOG_DIR%\%LASTLOG%' -Tail 30"

)

echo ------------------------------------------------

echo.

call :PAUSE_IF

exit /b 0



REM ============================================================

REM  子程序：档位 -> 参数

REM ============================================================

:APPLY_TIER

set "CTX="

if "%TIER%"=="1" ( set "CTX=32768"  & set "THREADS=16" & set "OUT=8192"  & set "TIER_NAME=短任务档"   & set "NEED_GB=24" )

if "%TIER%"=="2" ( set "CTX=49152"  & set "THREADS=16" & set "OUT=12288" & set "TIER_NAME=中档"       & set "NEED_GB=24" )

if "%TIER%"=="3" ( set "CTX=65536"  & set "THREADS=16" & set "OUT=16384" & set "TIER_NAME=标准档"     & set "NEED_GB=24" )

if "%TIER%"=="4" ( set "CTX=98304"  & set "THREADS=16" & set "OUT=24576" & set "TIER_NAME=长文档档"   & set "NEED_GB=25" )

if "%TIER%"=="5" ( set "CTX=131072" & set "THREADS=16" & set "OUT=32768" & set "TIER_NAME=超长档"     & set "NEED_GB=25" )

if "%TIER%"=="6" ( set "CTX=163840" & set "THREADS=16" & set "OUT=40960" & set "TIER_NAME=长上下文档" & set "NEED_GB=26" )

if "%TIER%"=="7" ( set "CTX=196608" & set "THREADS=16" & set "OUT=49152" & set "TIER_NAME=极限档"     & set "NEED_GB=26" )

exit /b 0



REM ============================================================

REM  子程序：按当前可用内存列出各档位可行性

REM ============================================================

:SHOW_TIER_FIT
echo   当前机器/total %TOTAL_GB% GB，可用/free %FREE_GB% GB，本模型 "%MODEL_LABEL%" 下的档位情况 / tiers that fit：
call :FIT_LINE 1 短任务档   32768
call :FIT_LINE 2 中档       49152
call :FIT_LINE 3 标准档     65536
call :FIT_LINE 4 长文档档   98304
call :FIT_LINE 5 超长档     131072
call :FIT_LINE 6 长上下文档 163840
call :FIT_LINE 7 极限档     196608
exit /b 0


:FIT_LINE
REM 入参：%~1 = 档位号，%~2 = 档位名，%~3 = 上下文大小
call :NEED_FOR_CTX %~3
set /a FIT_NEED=%NEED_GB% * 1024
if %FREE_MB% LSS %FIT_NEED% echo        内存不足   档位 %~1  %~2   需 %NEED_GB% GB
if %FREE_MB% GEQ %FIT_NEED% echo        可用       档位 %~1  %~2   需 %NEED_GB% GB
exit /b 0


:TIER_HINT

set "REC_TIER="

set "REC_TIER_NAME="

set "REC_CTX_HINT="

set "VRH="

REM 注意：整条 nvidia-smi 命令要用双引号包起来 —— for /f 里 cmd 会把

REM --format=csv,noheader,nounits 的逗号拆散，导致 nvidia-smi 报「noheader 无法识别」。

for /f "usebackq tokens=1 delims=, " %%a in (`"nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits" 2^>nul`) do (

  if not defined VRH set "VRH=%%a"

)

if not defined VRH exit /b 0

set /a VRH=%VRH% 2>nul

if not defined VRH exit /b 0

if %VRH% LEQ 0 exit /b 0

REM 16 GB 显存档直接给 192K（2026-10-22 按 8G 实测参数外推）：
REM   16 GB / 192K 预算 = 16384 - 其它 ~400 - compute 900 - KV(q8 1966) - 96 = 13022 MiB，
REM   非专家 40 层占 1600，剩 11422 给专家 → 16 层（上限 16），余量仍有 3422 MiB。
REM   实测峰值推算约 12400 MiB，也就是 16 GB 卡上还剩 4 GB 左右，正好拿来换上下文。
REM 24 GB 及以上同档（192K 已是本模型原生窗口的 73%，再大没有收益）。
if %VRH% GEQ 15000 ( set "REC_TIER=7" & set "REC_TIER_NAME=极限档"     & set "REC_CTX_HINT=192K" & exit /b 0 )

if %VRH% GEQ 11000 ( set "REC_TIER=5" & set "REC_TIER_NAME=超长档"     & set "REC_CTX_HINT=128K" & exit /b 0 )

if %VRH% GEQ 7000  ( set "REC_TIER=4" & set "REC_TIER_NAME=长文档档"   & set "REC_CTX_HINT=96K"  & exit /b 0 )

if %VRH% GEQ 3000  ( set "REC_TIER=3" & set "REC_TIER_NAME=标准档"     & set "REC_CTX_HINT=64K"  & exit /b 0 )

set "REC_TIER=1"

set "REC_TIER_NAME=短任务档"

set "REC_CTX_HINT=32K"

exit /b 0



REM ============================================================

REM  子程序：解析实际要用的模型文件

REM  只用官方 Q4_K_M 与 IQ3_S 两种量化（Q4_K_XL 已停用，不再探测），谁存在就用谁，

REM  同时设置档位菜单里显示的模型名。都不在时保持默认 Q4 路径，

REM  由 MODEL_GATE 引导下载后再重新解析。

REM  有效性判定：文件存在且不小于 1 GB（两个官方量化都 >12 GB）。

REM  不足 1 GB 按损坏/不完整处理 —— 会被重新下载覆盖，避免一个

REM  下载失败留下的残留文件把「有模型」的检测骗过去。

REM ============================================================

:MODEL_DETECT
REM 两种量化都能直接用：Q4_K_M 约 20.6 GB（32G 内存，最多 64K），
REM IQ3_S 约 12.7 GB（16G 内存 + 4G 显存，最多 64K）。
set "MODEL_DIR=%ROOT%llama.cpp\models"
set "MODEL_VALID="
call :MD_TRY "Qwen3.6-35B-A3B-UD-Q4_K_M.gguf"
if defined MODEL_VALID exit /b 0
call :MD_TRY "Qwen3.6-35B-A3B-UD-IQ3_S.gguf"
if defined MODEL_VALID exit /b 0
REM 一个都没有：把 MODEL 指到默认要下载的那份，后面由 MODEL_GATE 引导下载
set "MODEL=%MODEL_DIR%\Qwen3.6-35B-A3B-UD-Q4_K_M.gguf"
set "MODEL_LABEL=Qwen3.6-35B-A3B-UD-Q4_K_M（尚未下载 / not downloaded yet）"
exit /b 0


:MD_TRY
REM 入参：%~1 = 文件名，%~2 = 显示标签
REM 出参：MODEL_VALID / MODEL / MODEL_LABEL / MODEL_MB（MiB 整数）
set "MD_FILE=%MODEL_DIR%\%~1"
if not exist "%MD_FILE%" exit /b 0
set "MD_RAW="
REM 一次 PowerShell 同时完成「够不够 1 GB」与「大小多少 MiB」：
REM 省掉后面再单独调一次 PowerShell 取大小（每次冷启动约 0.2~0.4 s）。
REM 输出形如 OK20251（够 1 GB）或 SMALL；加前缀是为了能校验 ——
REM 万一路径不存在等导致外部程序吐错，也不会把非数字塞进 if 的数值比较里
REM （那会报「此时不应有 ...」并把整段流程带停）。
for /f "usebackq delims=" %%a in (`powershell -NoProfile -Command "$l=(Get-Item -LiteralPath '%MD_FILE%').Length; if($l -ge 1073741824){'OK'+[string][int][math]::Round($l/1MB)}else{'SMALL'}"`) do set "MD_RAW=%%a"
if not defined MD_RAW exit /b 0
if /i "%MD_RAW%"=="SMALL" goto :MD_TRY_BAD
if not "%MD_RAW:~0,2%"=="OK" goto :MD_TRY_BAD
set "MD_MB=%MD_RAW:~2%"
if not defined MD_MB goto :MD_TRY_BAD
if %MD_MB% LSS 1024 goto :MD_TRY_BAD
set "MODEL_VALID=1"
set "MODEL=%MD_FILE%"
set "MODEL_MB=%MD_MB%"
REM 标签体积按实际文件算（GiB，一位小数四舍五入）：菜单、检查项、内存需求
REM 三处口径一致，不会出现「菜单 22.4 GB、检查 19.7 GB」这种自相矛盾。
set /a MD_GB10=(%MD_MB% * 10 + 512) / 1024
set "MODEL_GB=%MD_GB10:~0,-1%.%MD_GB10:~-1%"
set "MODEL_LABEL=%~n1（MoE，无 MTP，%MODEL_GB% GB）"
exit /b 0
:MD_TRY_BAD
  if not defined MD_WARNED echo         [警告]  %~1 不足 1 GB，判定为损坏或不完整，将重新下载覆盖
  if not defined MD_WARNED set "MD_WARNED=1"
exit /b 0


:SHOW_MODEL_SIZE
REM 体积已由 MD_TRY 算好（MODEL_GB），这里不再调外部程序，也不重复换算。
if not defined MODEL_GB set "MODEL_GB=?"
:SMS_OUT
echo         大小/Size %MODEL_GB% GB（Q4 级别完整约 20 GB / a full Q4 is about 20 GB，明显偏小说明文件损坏 / much smaller means corrupt）
exit /b 0


:MODEL_GATE

if defined MODEL_GATE_DONE exit /b 0

call :MODEL_DETECT

if defined MODEL_VALID (

  set "MODEL_GATE_DONE=1"

  exit /b 0

)

if "%QUIET%"=="1" (

  set "MODEL_GATE_DONE=1"

  exit /b 0

)

if not exist "%SystemRoot%\System32\curl.exe" goto :MG_NOCURL

if not exist "%MODEL_DIR%" mkdir "%MODEL_DIR%" >nul 2>nul



:MG_MENU

REM 重试上限：输入流耗尽（管道/重定向到文件尾）时会不断走默认值，

REM 这里封顶 6 轮，保证任何输入情况下都能退出而不是死循环。

set /a MG_ROUND+=1

if %MG_ROUND% GEQ 6 (

  echo.

  echo   [提示/HINT] 选择次数过多，退出下载引导 / too many invalid inputs, leaving the download guide. 可重新运行本脚本再试 / run again to retry，

  echo         或按/or see llama.cpp\models\下载模型.md 手动下载 / download manually.

  echo.

  set "MODEL_GATE_ABORT=1"

  set "MODEL_GATE_DONE=1"

  exit /b 0

)

cls

echo ============================================================

echo   未检测到模型文件，需要先下载模型 / No model file found, download it first

echo ============================================================

echo   模型目录/MODEL DIR   %MODEL_DIR%

echo   来源/SOURCE       https://hf-mirror.com/unsloth/Qwen3.6-35B-A3B-GGUF

echo.

echo   请选择量化版本 / Choose a quantization（二选一/pick one，下载一次以后不再询问 / asked only once）：

echo.

echo ------------------------------------------------------------

echo   1   IQ3_S     ~12.74 GB    16G 内存设备首选 / best for 16 GB RAM（有 4G 以上显存更宽松 / 4G+ VRAM makes it roomier）

echo   2   Q4_K_M    ~20.61 GB    推荐 / recommended（32G 内存 / 32 GB RAM，质量更好 / better quality）

echo.

echo   0   退出/Exit（可稍后手动下载 / download manually later）

echo ------------------------------------------------------------

echo.

set "DL="

set /p "DL=  请输入编号/Enter number [2] : "

REM 只取首个字符：万一输入来源异常（例如被管道塞进含换行的多行

REM 文本），变量携带换行会把后面的 if 比较行拆散、报"命令语法不

REM 正确"。正常控制台回车输入只会有 0/1/2，截首字符无副作用。

set "DL=%DL:~0,1%"

if "%DL%"=="" set "DL=2"

if "%DL%"=="0" (

  set "MODEL_GATE_DONE=1"

  set "MODEL_GATE_ABORT=1"

  exit /b 0

)

if "%DL%"=="1" goto :MG_PICK_IQ3

if "%DL%"=="2" goto :MG_PICK_Q4

goto :MG_MENU



:MG_PICK_IQ3

set "DL_NAME=Qwen3.6-35B-A3B-UD-IQ3_S.gguf"

set "DL_SIZE=12.74"

set "DL_BYTES=13676723168"

set "DL_NEED_GB=14"

goto :MG_CONFIRM



:MG_PICK_Q4

set "DL_NAME=Qwen3.6-35B-A3B-UD-Q4_K_M.gguf"

set "DL_SIZE=20.61"

set "DL_BYTES=22134528992"

set "DL_NEED_GB=22"

goto :MG_CONFIRM



REM ------------------------------------------------------------

REM  下载前确认：磁盘空间预检 + 明确来源与目标

REM ------------------------------------------------------------

:MG_CONFIRM

set "MDL=%MODEL_DIR:~0,1%"

set "MDL_FREE_GB=?"

for /f "usebackq delims=" %%a in (`powershell -NoProfile -Command "[int]((Get-PSDrive -Name '%MDL%' -ErrorAction SilentlyContinue).Free/1GB)"`) do set "MDL_FREE_GB=%%a"

echo.

echo   即将下载 / About to download   %DL_NAME%（约/~%DL_SIZE% GB）

echo   保存到 / Save to     %MODEL_DIR%\%DL_NAME%

if "%MDL_FREE_GB%"=="?" (

  echo   磁盘/DISK   读不到/cannot read %MDL%: 盘剩余空间，请自行确认充足 / please make sure there is enough free space

) else (

  if %MDL_FREE_GB% LSS %DL_NEED_GB% (

    echo.

    echo   [失败/FAIL] %MDL%: 盘仅剩/only %MDL_FREE_GB% GB left，装不下约/cannot fit ~%DL_SIZE% GB 的模型/model

    echo          （需要约/needs ~%DL_NEED_GB% GB）。可改选/pick 1（IQ3_S）或清理磁盘后重试 / or free up disk space and retry.

    echo.

    call :PAUSE_IF

    goto :MG_MENU

  )

  echo   磁盘/DISK   %MDL%: 盘剩余/free %MDL_FREE_GB% GB（需要约/needs ~%DL_NEED_GB% GB）

)

echo.

echo   下载支持断点续传 / Resumable download：中断后重新运行本脚本会接着下载 / interrupting is safe, it resumes.

echo   文件较大，所需时间取决于网速 / large file, time depends on your bandwidth，请等进度条走完 / wait for the progress bar.

echo.

set "YN="

set /p "YN=  确认开始下载吗？/ Start the download? (Y/n) : "

REM 同上：只取首个字符，防止异常输入携带换行拆散后续 if 行

set "YN=%YN:~0,1%"

if /i "%YN%"=="n" goto :MG_MENU



REM ------------------------------------------------------------

REM  正式下载：curl -L -C - 断点续传，落到 .part，校验后改名

REM ------------------------------------------------------------

:MG_DL

set "DST=%MODEL_DIR%\%DL_NAME%"

set "PART=%MODEL_DIR%\%DL_NAME%.part"

set "DL_RC=0"

echo.

echo [信息/INFO] 开始下载/Downloading：%DL_NAME%

if exist "%PART%" echo [信息] 发现未完成的下载，将从断点继续

REM .part 已达官方大小：直接采用，不再发起请求

set "PART_BIG="

if exist "%PART%" (

  for /f "usebackq delims=" %%a in (`powershell -NoProfile -Command "if((Get-Item -LiteralPath '%PART%' -ErrorAction SilentlyContinue).Length -ge %DL_BYTES%){'BIG'}"`) do set "PART_BIG=%%a"

)

if "%PART_BIG%"=="BIG" goto :MG_ADOPT

curl -L -C - --retry 3 --retry-delay 5 -o "%PART%" "https://hf-mirror.com/unsloth/Qwen3.6-35B-A3B-GGUF/resolve/main/%DL_NAME%"

set "DL_RC=%errorlevel%"

if not "%DL_RC%"=="0" goto :MG_DL_FAIL



:MG_ADOPT

if not exist "%PART%" goto :MG_DL_FAIL

move /y "%PART%" "%DST%" >nul 2>nul

if not exist "%DST%" goto :MG_DL_FAIL

REM 大小校验：与官方发布的精确字节数比对，偏差超过 1% 视为不完整

set "DL_CHK="

for /f "usebackq delims=" %%a in (`powershell -NoProfile -Command "$s=(Get-Item -LiteralPath '%DST%').Length; $e=%DL_BYTES%; if([math]::Abs($s-$e) -lt ($e/100)){'OK'}"`) do set "DL_CHK=%%a

if not "%DL_CHK%"=="OK" goto :MG_DL_BADSIZE

for /f "usebackq delims=" %%a in (`powershell -NoProfile -Command "[math]::Round((Get-Item -LiteralPath '%DST%').Length/1GB,2)"`) do set "DL_GOT_GB=%%a"

echo.

echo ============================================================

echo   下载完成，模型已就绪 / Download finished, model is ready

echo ============================================================

echo   文件/File   %DST%

echo   大小/Size   %DL_GOT_GB% GB（与官方发布值一致 / matches the official size）

echo   提示/HINT   需要图片理解的话 / for image input，还需下载/also download mmproj-BF16.gguf（0.84 GB）

echo.

echo   按回车进入档位选择 / press Enter to choose a tier.

echo ============================================================

call :PAUSE_IF

call :MODEL_DETECT

set "MODEL_GATE_DONE=1"

exit /b 0



:MG_DL_FAIL

echo.

echo [错误/ERROR] 下载未完成 / download incomplete（curl 退出码/exit code %DL_RC%）.

echo        常见原因 / usual causes：网络中断/network drop、镜像站限流/rate limit、磁盘空间不足/disk full.

echo        已下载的部分保留在 / partial file kept at %PART%，

echo        重新运行本脚本会从断点继续 / run again to resume，也可按 下载模型.md 手动下载 / or download manually.

echo.

call :PAUSE_IF

goto :MG_MENU



:MG_DL_BADSIZE

echo.

echo [错误/ERROR] 文件大小与官方发布值不符 / file size does not match the official value，下载可能不完整 / download may be incomplete.

echo        请删除/delete %DST% 后重试/and retry，或按 下载模型.md 手动下载 / or download manually.

echo.

call :PAUSE_IF

goto :MG_MENU



:MG_NOCURL

echo.

echo [错误/ERROR] 未找到系统自带 curl / curl.exe not found（%SystemRoot%\System32\curl.exe），无法自动下载 / cannot auto-download.

echo        请按/see llama.cpp\models\下载模型.md 手动下载模型 / download manually，放到/put it in：

echo        %MODEL_DIR%

echo.

set "MODEL_GATE_ABORT=1"

set "MODEL_GATE_DONE=1"

exit /b 0



REM ============================================================

REM  子程序：检测服务进程

REM ============================================================

:DETECT

set "SRV_PID="

for /f "usebackq delims=" %%a in (`powershell -NoProfile -Command "$p=@(Get-Process -Name llama-server -ErrorAction SilentlyContinue); if($p.Count -gt 0){$p[0].Id}"`) do set "SRV_PID=%%a"

exit /b 0



REM ============================================================

REM  子程序：端口状态（free / busy）

REM ============================================================

:PORT_BUSY

set "PORT_STATE=free"

set "PORT_PID="

for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%PORT% " ^| findstr /I "LISTENING"') do (

  set "PORT_PID=%%a"

  set "PORT_STATE=busy"

)

if not defined PORT_PID set "PORT_STATE=free"

exit /b 0



REM ============================================================

REM  子程序：读取上次启动记录

REM ============================================================

:LOAD_PIDFILE

set "CUR_PID="

set "CUR_TIER="

set "CUR_CTX="

set "CUR_T="

set "CUR_TIME="

set "CUR_THINK=off"

set "CUR_GPU=off"

set "CUR_GPU_ARGS="

set "CUR_TIER_NAME=未知档位"

if not exist "%PID_FILE%" exit /b 0

for /f "usebackq tokens=1-8 delims=|" %%a in ("%PID_FILE%") do (

  set "CUR_PID=%%a"

  set "CUR_TIER=%%b"

  set "CUR_CTX=%%c"

  set "CUR_T=%%d"

  set "CUR_TIME=%%e"

  set "CUR_THINK=%%f"

  set "CUR_GPU=%%g"

  set "CUR_GPU_ARGS=%%h"

)

if not defined CUR_THINK set "CUR_THINK=off"

if not defined CUR_GPU set "CUR_GPU=off"

if "%CUR_TIER%"=="1" set "CUR_TIER_NAME=短任务档"

if "%CUR_TIER%"=="2" set "CUR_TIER_NAME=中档"

if "%CUR_TIER%"=="3" set "CUR_TIER_NAME=标准档"

if "%CUR_TIER%"=="4" set "CUR_TIER_NAME=长文档档"

if "%CUR_TIER%"=="5" set "CUR_TIER_NAME=超长档"

if "%CUR_TIER%"=="6" set "CUR_TIER_NAME=长上下文档"

if "%CUR_TIER%"=="7" set "CUR_TIER_NAME=极限档"

REM 输出建议 = 上下文 ÷ 4（与 :APPLY_TIER 的 OUT 同口径），供 status 显示 / 填客户端 max_tokens

if defined CUR_CTX set /a CUR_OUT=%CUR_CTX% / 4

exit /b 0



REM ============================================================

REM  子程序：确保访问密钥存在（首次运行自动生成，不覆盖已有文件）

REM ============================================================

:ENSURE_KEY
REM 只在缺文件时创建；已有文件（用户可能自己加了多把密钥）绝不覆盖。
if exist "%KEY_FILE%" exit /b 0
call :GEN_KEY
exit /b 0


:GEN_KEY
REM 生成一把新密钥并（重新）写入密钥文件；成功 exit /b 0，失败 exit /b 1
set "NEWKEY="
for /f "usebackq delims=" %%a in (`powershell -NoProfile -Command "[guid]::NewGuid().ToString('N')"`) do set "NEWKEY=%%a"
if not defined NEWKEY exit /b 1
(
echo # llama.cpp 服务访问密钥 / API keys（局域网设备调用时必须携带 / required for LAN calls）
echo # 每行一个密钥 / one key per line，可写多行做轮换 / rotate by adding more；以井号开头的行是注释 / lines starting with # are comments.
echo # 修改后需重启服务才生效 / restart the service to apply。文件位置/File：%KEY_FILE%
echo %NEWKEY%
) > "%KEY_FILE%"
exit /b 0
:ASK_KEY
REM 启动前最后一次询问：要不要换一把新的访问密钥。
REM 放在「启动之前」而不是「启动之后」：密钥是启动时以 --api-key 参数传给
REM llama-server 的，只有这里选 y 才会对本次服务立刻生效（启动后再改得重启服务）。
REM 无论选 y 还是 n，启动成功后的 API 信息里都会再展示一次密钥，不怕忘。
REM 静默模式（quiet）与「输入耗尽」都取默认值 n = 沿用，脚本化调用不受影响。
if "%QUIET%"=="1" exit /b 0
call :ENSURE_KEY
call :LOAD_KEY
echo.
echo ------------------------------------------------------------
echo   访问密钥 / API KEY
echo ------------------------------------------------------------
if defined API_KEY echo   当前密钥/CURRENT   %API_KEY%
if not defined API_KEY echo   当前密钥/CURRENT   ^(尚无，将自动创建 / none yet, will be created^)
echo.
set "AK="
echo   说明/NOTE：选 y 会用新密钥覆盖密钥文件（文件里其它密钥也会被清掉）/ y overwrites the key file
set /p "AK=  是否生成新的 API Key？/ Generate a new API key? (y/N) : "
set "AK=%AK:~0,1%"
if /i "%AK%"=="y" goto :AK_NEW
echo   沿用现有密钥/KEEP    %API_KEY%
echo                       ^(启动成功后还会展示一次 / shown again after startup^)
exit /b 0
:AK_NEW
call :GEN_KEY
if errorlevel 1 goto :AK_FAIL
call :LOAD_KEY
echo   已生成新密钥/NEW KEY  %API_KEY%
echo                       ^(启动成功后还会展示一次 / shown again after startup^)
exit /b 0
:AK_FAIL
echo   [提示/HINT] 生成失败，继续沿用原密钥 / generation failed, keeping the current key
exit /b 0


:LOAD_KEY

set "API_KEY="

if not exist "%KEY_FILE%" exit /b 0

for /f "usebackq delims=" %%a in (`findstr /v "^#" "%KEY_FILE%"`) do call :APPEND_KEY "%%a"

exit /b 0



:APPEND_KEY

if not defined API_KEY goto :AK_FIRST

set "API_KEY=%API_KEY%,%~1"

exit /b 0



:AK_FIRST

set "API_KEY=%~1"

exit /b 0



REM ============================================================

REM  子程序：获取局域网 IPv4（排除回环与 169.254 自动私有地址）

REM  说明：PowerShell 里要用管道，先落临时文件再读，

REM        避免 for /f 反引号内管道转义的老问题。

REM ============================================================

:GET_LAN_IP

set "LAN_IP="

set "IPTMP=%TEMP%\llm_lan_ip.txt"

powershell -NoProfile -Command "$a=Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue; foreach($i in $a){ if($i.IPAddress -notlike '127.*' -and $i.IPAddress -notlike '169.254.*'){ Write-Output $i.IPAddress; break } }" > "%IPTMP%" 2>nul

if exist "%IPTMP%" (

  for /f "usebackq delims=" %%a in ("%IPTMP%") do if not defined LAN_IP set "LAN_IP=%%a"

  del "%IPTMP%" >nul 2>nul

)

exit /b 0



REM ============================================================

REM  子程序：探测可用 GPU

REM

REM  判定依据是 llama-server --list-devices 的实际输出 —— 它来自后端本身，

REM  报的是「该后端真正能用的显存」，比 WMI / 注册表可靠得多

REM  （WMI 的 AdapterRAM 在 >4 GB 时会溢出，注册表值不反映当前占用）。

REM

REM  包里只编 CUDA 后端，所以「列表里有设备」等价于「有可用的 N 卡」；

REM  核显与非 N 卡根本不会出现在列表里，无需额外排除逻辑。

REM

REM  以下任一情况都会让列表解析不出内容 → GPU_AVAILABLE=0

REM  → 自动退回纯 CPU，不阻断启动：

REM    没有 ggml-cuda.dll / 没有 N 卡 / 驱动过老 /

REM    缺 CUDA 运行库(cublas) / 后端 API 版本不匹配

REM

REM  注意（踩过一次的坑）：重定向会先把输出文件建出来，所以

REM  「文件存在」并不能说明探测成功，必须靠「解析出来的内容是否为空」判断。

REM ============================================================

:GPU_PROBE

REM 同一轮里可能被调用两次（检查项一次、启动前一次），结果缓存起来避免重复探测

if "%GPU_PROBED%"=="1" exit /b 0

set "GPU_PROBED=1"

set "GPU_AVAILABLE=0"

set "GPU_NAME="

set "GPU_DEV_ID="

set "GPU_DEV_IDS="

set "GPU_TOTAL_MIB=0"

set "GPU_FREE_MIB=0"

set "GPU_PROBE_NOTE="

if not exist "%BIN_DIR%\ggml-cuda.dll" (

  set "GPU_PROBE_NOTE=未找到 CUDA 后端 ggml-cuda.dll（见 环境检查_EnvCheck.bat 第 11 项）"

  exit /b 0

)

REM stdout 与 stderr 都收：设备列表走 stdout，后端的告警走 stderr

set "GPUTMP=%TEMP%\llm_gpu_probe.txt"

"%SERVER_EXE%" --list-devices > "%GPUTMP%" 2>&1

call :CP_RESET

REM 解析形如：  CUDA0: NVIDIA GeForce GTX 1660 (6144 MiB, 5312 MiB free)

REM 四组：设备名 / 型号描述 / 总显存 / 空闲显存。收集全部设备，

REM 主设备取第一台，全部设备名供 manual 模式的 --device 校验用。

for /f "usebackq delims=" %%a in (`powershell -NoProfile -Command "$t=Get-Content -LiteralPath '%GPUTMP%' -ErrorAction SilentlyContinue; foreach($l in $t){ if($l -match '^\s*([^:\s]+)\s*:\s*(.+?)\s*\((\d+)\s*MiB,\s*(\d+)\s*MiB free\)'){ Write-Output ($matches[1] + '|' + $matches[2] + '|' + $matches[3] + '|' + $matches[4]) } }"`) do call :GPU_TAKE "%%a"

del "%GPUTMP%" >nul 2>nul

if not defined GPU_DEV_ID (

  call :GPU_WHY

  exit /b 0

)

REM 其它程序已占用的显存：此刻 llama-server 还没起来，nvidia-smi 报的 used

REM 就是桌面 / 浏览器 / 视频等占用的部分。显存预算要把这块扣掉 ——

REM Windows 没有「锁定显存」的接口，能做的就是「算准 + 留出安全垫 + 提醒关掉占用大户」。

set "GPU_OTHER_MIB=0"

for /f "usebackq tokens=1 delims=, " %%a in (`"nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits" 2^>nul`) do set "GPU_OTHER_MIB=%%a"

set "GPU_OTHER_NOTE="

if %GPU_OTHER_MIB% GTR 600 set "GPU_OTHER_NOTE=其它程序已占用 %GPU_OTHER_MIB% MiB 显存，建议先关掉浏览器/视频/游戏再启动 / %GPU_OTHER_MIB% MiB VRAM is held by other apps: close browsers/video/games first"

set "GPU_AVAILABLE=1"

exit /b 0



:GPU_TAKE

for /f "tokens=1,2,3,4 delims=|" %%a in ("%~1") do call :GPU_TAKE_ONE "%%a" "%%b" "%%c" "%%d"

exit /b 0



REM 这里必须用 call 逐条处理：for 循环体内的 %VAR% 在整块解析时只展开一次，

REM 直接写 set "GPU_DEV_IDS=%GPU_DEV_IDS% ..." 会丢掉前面的累积结果。

:GPU_TAKE_ONE

if not defined GPU_DEV_ID (

  set "GPU_DEV_ID=%~1"

  set "GPU_NAME=%~2"

  set "GPU_TOTAL_MIB=%~3"

  set "GPU_FREE_MIB=%~4"

)

set "GPU_DEV_IDS=%GPU_DEV_IDS% %~1"

exit /b 0



REM ============================================================

REM  子程序：探测不到设备时细分原因

REM  旧卡用户最常缺的是 CUDA 运行库 —— 它不随显卡驱动安装，

REM  只给一句「后端未列出设备」会让人无从下手。

REM

REM  运行库的查找顺序与 Windows 的 DLL 解析一致：先看 bin\（exe 同目录），

REM  再看 PATH。装过 CUDA / PyTorch 的机器往往只有 PATH 里有。

REM ============================================================

:GPU_WHY

call :GPU_LIB_OK cublas64_12.dll

set "GW_A=%GW_LIB_OK%"

call :GPU_LIB_OK cublasLt64_12.dll

set "GW_B=%GW_LIB_OK%"

if "%GW_A%%GW_B%"=="11" goto :GW_NEXT

set "GPU_PROBE_NOTE=缺 CUDA 运行库 cublas64_12.dll / cublasLt64_12.dll，后端无法加载"

exit /b 0

:GW_NEXT

if not exist "%SystemRoot%\System32\nvcuda.dll" (

  set "GPU_PROBE_NOTE=缺少 nvcuda.dll：NVIDIA 显卡驱动没装好或版本过老"

  exit /b 0

)

set "GPU_PROBE_NOTE=后端没认出设备：驱动过老、后端与运行库版本不匹配、或本机确实没有 N 卡"

exit /b 0



:GPU_LIB_OK

set "GW_LIB_OK=0"

if exist "%BIN_DIR%\%~1" set "GW_LIB_OK=1"

if "%GW_LIB_OK%"=="1" exit /b 0

where %~1 >nul 2>nul

if not errorlevel 1 set "GW_LIB_OK=1"

exit /b 0



REM ============================================================

REM  子程序：把控制台代码页改回 936

REM

REM  必须调：llama-server 启动时会在 common_init() 里执行

REM  SetConsoleOutputCP(CP_UTF8) / SetConsoleCP(CP_UTF8)，

REM  而探测是在「本脚本所在的这个控制台」里跑的，于是它把整个窗口

REM  的代码页改成了 65001 —— 之后本脚本用 GBK 写的中文全部变成乱码

REM  （连 pause 的提示都会变英文）。实测 936 -> 65001。

REM  所以每次在控制台里调用过 llama-server 之后都要改回来。

REM ============================================================

:CP_RESET

chcp 936 <nul >nul 2>nul

exit /b 0



REM ============================================================

REM  子程序：按模式组装 GPU 参数

REM

REM  auto 模式的核心组合是「--n-gpu-layers N --cpu-moe」：

REM    --cpu-moe      把体积最大的 MoE 专家权重留在内存

REM                   （占模型 88.1%，每 token 只激活 8/256）

REM    --n-gpu-layers 于是上显存的只有「每 token 必读」的注意力/稠密/输出等，

REM                   本模型全量是 2.53 GiB；N 表示前 N 层上显存

REM  为什么不用 --fit 自动决定 N：见 auto 分支里的实测说明（它会放弃，

REM  然后把全部层塞进显存，速度反而掉到 1/2.4）。

REM ============================================================

:BUILD_GPU_ARGS

set "GPU_ARGS=--n-gpu-layers 0"

set "GPU_STRATEGY=纯 CPU"

if /i "%GPU_MODE%"=="off" (

  set "GPU_STRATEGY=纯 CPU（GPU_MODE=off，已手动关闭）"

  exit /b 0

)

if "%GPU_AVAILABLE%"=="1" goto :BGA_HAVE

set "GPU_STRATEGY=纯 CPU（已请求 GPU 但不可用，已自动退回）"

exit /b 0



:BGA_HAVE

if /i "%GPU_MODE%"=="manual" goto :BGA_MANUAL

REM ---------- auto ----------

REM 8 GB 及以上：ub 2048（prefill 少搬一半 PCIe）+ compute 预算同步上调到 900 MiB。
REM 实测 compute 缓冲从 660（ub1024）涨到 914（ub2048），预算里只写 600 会算多一层 → 贴顶分页。
REM 6 GB 及以下不跟：那条路线是 --cpu-moe（MoE 全在 CPU），ub 2048 实测反而慢 10%。
if %GPU_TOTAL_MIB% GEQ %GPU_BAND_HIGH_UB% set "UB=2048"

if %GPU_TOTAL_MIB% GEQ %GPU_BAND_HIGH_UB% set "GPU_FIXED_MIB=900"

REM 3~4 GB 带覆盖成实测的 620（见上方 GPU_FIXED_MIB 的扫点记录）。顺序统一为「先大卡、后小卡」。
if %GPU_TOTAL_MIB% LEQ %GPU_BAND_SMALL% set "GPU_FIXED_MIB=620"

REM 0.3.3 起取消「中端显存带强制 q8_0 KV + 视觉塔常驻」这条**组合**策略。它的前提
REM 「显存越大、上显存的专家层越多越划算」在 2026-10-22 被 8 GB 卡实测推翻：7 层专家
REM （3.5 GiB）把 prefill 需要的临时缓冲挤没了（prefill 从 200 多崩到 8.4 t/s）。
REM 但拆开来看，两条子策略的结论不同，不要一起丢掉：
REM   - KV 精度：**保留强制 q8_0**（见下方 BGA_FORCE_Q8）。这是本项目的设计口径，
REM     低性能设备不用全精度 KV，省下的一半显存正是留给权重与计算缓冲的。
REM   - 视觉塔常驻：**取消**。改为 MMPROJ_OFFLOAD=host（放系统内存，不占专用显存），
REM     预算里也就不再扣它 930~1134 MiB。
REM 专家层按显存分带设上限（见 BGA_ECAP），实测细节见 参数阶梯手册_TierManual.md 的「0.3.4 · 三个性能开关与线程数」一节。
set "BGA_LOW_LAYERS="

REM 这里刻意不用 --fit，原因见下方注释；改为自己按显存余量算卸几层。

REM

REM 为什么不用 --fit（2026-10-15 在 GTX 1060 3GB 上实测踩到）：

REM   --cpu-moe 会设置「张量缓冲区覆盖」，而 --fit 一旦发现用户已设置覆盖

REM   就直接放弃（日志原文：failed to fit params ... tensor_buft_overrides

REM   already set by user, abort）。放弃之后 n_gpu_layers 落到「全部层」，

REM   于是 42/42 层全塞进显存 —— 需要 3036 MiB，可用仅 2208 MiB，

REM   WDDM 只能把显存分页到系统内存，生成速度从 14.6 掉到 6.1 t/s。

REM

REM 换成自己算，实测有效（16K 上下文、GTX 1060 3GB，生成速度 t/s）：

REM   0 层 14.5 / 32 层 19.5 / 36 层 18.8 / 38 层 19.8 / 40 层 20.8 / 41 层 21.4

REM   加 -nkvo（KV 留内存）只剩 14.9 —— 等于没收益，所以 KV 必须留在显存。

REM   32 层往上速度基本持平，所以直接压到模型层数上限最划算。

REM 层数按「显卡总显存」算，不是按 llama.cpp 报的空闲显存：

REM   它的 free 会额外扣掉一份保留量（本卡报 2460，实际可用约 2880），

REM   用 total 才算得满。代价是没留余量 —— 若同时开着重度图形程序把桌面

REM   占用推高，仍可能越界分页（分页后速度掉到约 1/2.4）；想留量就调大

REM   GPU_RESERVE_MIB。

if %GPU_FREE_MIB% LSS %GPU_MIN_FREE_MIB% goto :BGA_SMALL

if not defined GPU_TOTAL_MIB goto :BGA_SMALL

REM 专家层硬上限：按显存分带。写法是从高往低逐个覆盖，低带写在后面 —— 8192 会
REM 命中最后一行取 T1，12288 取 T2，16384 取 T3，20000 及以上保持 40（不设限）。
REM 为什么必须设上限：8 GB 卡把 7 层专家塞进显存后，KV + 视觉塔 + 计算缓冲一起
REM 越界，WDDM 静默分页，prefill 从 200 多 t/s 崩到 8.4 t/s（2026-10-22 实测）。
set /a BGA_ECAP=%GPU_NLAYER%

if %GPU_TOTAL_MIB% LSS %GPU_VRAM_BAND_FULL% set /a BGA_ECAP=%GPU_EXPERT_CAP_T3%

if %GPU_TOTAL_MIB% LSS %GPU_VRAM_BAND_T3B% set /a BGA_ECAP=%GPU_EXPERT_CAP_T3B%

if %GPU_TOTAL_MIB% LSS %GPU_VRAM_BAND_T3% set /a BGA_ECAP=%GPU_EXPERT_CAP_T2%

if %GPU_TOTAL_MIB% LSS %GPU_VRAM_BAND_T2% set /a BGA_ECAP=%GPU_EXPERT_CAP_T1%

REM KV 精度：本项目面向低性能设备，KV 固定 q8_0，全档位无例外、不存在 f16 分支。
REM 理由不只是省显存（约省一半：96K 时 983 vs 1966 MiB），更因为 f16 KV 是
REM 「大显存卡不计代价」的旧路径，与本项目「把显存让给权重、把算力压给 CPU」
REM 的设计相反；且 q8_0 的精度代价实测只有约 0.7%。
REM 用单行 if 置位，不用 if ( ) 块（块内 %VAR% 展开取旧值，见 说明.md §3.8）。
set "BGA_FORCE_Q8=1"

REM --parallel 1：只开一个并发槽。本地单人使用用不上多槽，而它让 KV cache

REM 不再按 4 份分配 —— 实测 prefill 27.3 -> 33.5 t/s、生成 20.3 -> 21.4 t/s，

REM 还少占一点显存。

REM

REM 显存预算（逐项都实测过，启动信息里会打印出来）：

REM   可给权重 = 显存总量 - 其它程序占用 - 计算缓冲/上下文 - 视觉塔 - KV - 安全垫

REM   KV(f16) = 上下文/50 MiB，KV(q8_0) = 上下文/100 MiB
REM 本项目一律 q8_0（见上面 BGA_FORCE_Q8），全档位无 f16；f16 分支仅为兼容保留。

REM 注意：这里刻意全部写成一维语句、不用 if ( ) 块 —— 块内 set 过的变量在同一块里

REM 用 %VAR% 读会拿到旧值（见 说明.md §3.8），换个写法就不会踩这个坑。

if not defined CTX set "CTX=32768"

set "BGA_MMPROJ=%GPU_MMPROJ_MIB%"

if /i "%MMPROJ_SW%"=="off" set "BGA_MMPROJ=0"

if not exist "%MMPROJ%" set "BGA_MMPROJ=0"

REM 视觉塔走系统内存时，不占专用显存，预算里就不该扣它（这是本项目的设计口径）：

REM 它的 BF16 权重约 800 MiB，只在处理图片时参与计算，放内存对文本速度无影响。

if /i "%MMPROJ_OFFLOAD%"=="host" set "BGA_MMPROJ=0"

set "BGA_MMPROJ_AUTOOFF="

REM 视觉塔与层数只能二选一：mmproj 实测要吃约 930 MiB 专用显存。

REM 做法：先按「载」算一次 N 与 E，再按「不载」算一次，比较三种收益：

REM   1) 省下它能多上 GPU_MMPROJ_MIN_GAIN 层非专家权重（老口径，大显存卡仍用这条）；

REM   2) 省下它能多上 1 层以上专家（新口径，只在 8/12/16G 带生效）；

REM   3) 载着它余量不足 GPU_SLACK_MIN_MIB，会贴顶分页（新口径）。

REM 任一成立就不载，并在启动信息里说明。要处理图片把 MMPROJ_SW 设为 on 强制载入。

if /i not "%MMPROJ_SW%"=="auto" goto :BGA_MMP_DECIDED

if "%BGA_MMPROJ%"=="0" goto :BGA_MMP_DECIDED

call :BGA_CALC

call :BGA_MOE_CALC

set "BGA_N_WITH=%BGA_N%"

set "BGA_E_WITH=%BGA_EXPERT_GPU%"

set "BGA_SLACK_WITH=%BGA_SLACK%"

set "BGA_MMPROJ_KEEP=%BGA_MMPROJ%"

set "BGA_MMPROJ=0"

call :BGA_CALC

call :BGA_MOE_CALC

set /a BGA_MMP_GAIN=%BGA_N% - %BGA_N_WITH%

set /a BGA_MP_E_GAIN=%BGA_EXPERT_GPU% - %BGA_E_WITH%

REM 24G 及以上保持旧行为（只看非专家层数），不让新判据误伤大显存卡。

if %BGA_ECAP% GEQ %GPU_NLAYER% goto :BGA_MMP_LEGACY

if %BGA_MMP_GAIN% GEQ %GPU_MMPROJ_MIN_GAIN% goto :BGA_MMP_AUTOOFF

if %BGA_MP_E_GAIN% GEQ 1 goto :BGA_MMP_AUTOOFF

if %BGA_SLACK_WITH% LSS %GPU_SLACK_MIN_MIB% goto :BGA_MMP_AUTOOFF

goto :BGA_MMP_REVERT

:BGA_MMP_LEGACY

if %BGA_MMP_GAIN% LSS %GPU_MMPROJ_MIN_GAIN% goto :BGA_MMP_REVERT

:BGA_MMP_AUTOOFF

set "BGA_MMPROJ_AUTOOFF=1"

goto :BGA_MMP_DECIDED

:BGA_MMP_REVERT

set "BGA_MMPROJ=%BGA_MMPROJ_KEEP%"

:BGA_MMP_DECIDED

call :BGA_CALC

:BGA_PICK_DONE

REM 层数太少（< 8）时不值得上 GPU：几百 MiB 权重放显存，却仍要走 PCIe 取专家，
REM 收益为负。此时退回纯 CPU 并说明真实原因 —— 不能沿用「空闲显存不足」的文案，
REM 那种情况空闲显存明明是够的（只是本档位 KV 太大把权重挤没了）。
if %BGA_N% LSS 8 set "BGA_LOW_LAYERS=1"
if %BGA_N% LSS 8 goto :BGA_SMALL

if %BGA_N% GTR %GPU_NLAYER% set /a BGA_N=%GPU_NLAYER%

REM 非专家权重压满后还有剩余的显存，就拿来把「部分专家层」也搬上显存：

REM   --n-cpu-moe K 把「前 K 层」的专家权重留在 CPU，其余层专家上显存。

REM   K 越小 = 上显存的专家越多 = 解码越快。显存越大 K 越小 —— 这就是

REM   「同 CPU / DDR5 下，显存越大 token 越快」的着力点。

call :BGA_MOE_CALC

set "BGA_MOE_ARG=--cpu-moe"

if %BGA_NCMOE% LSS %GPU_NLAYER% set "BGA_MOE_ARG=--n-cpu-moe %BGA_NCMOE%"

if %BGA_NCMOE% LEQ 0 set "BGA_MOE_ARG="

REM 三个性能开关拼参数：全部用单行 if，不用 if ( ) 块 —— 块内 %VAR% 取旧值会拼错。
REM 参数追加在 --parallel 1 之后（check_budget 的表格裁剪依赖 "--parallel 1" 这个字面量）。
set "BGA_OPOFF_ARG="

if /i "%GPU_OPOFFLOAD%"=="off" set "BGA_OPOFF_ARG=--no-op-offload"

set "BGA_LOADMODE_ARG="

if /i "%GPU_LOADMODE%"=="none" set "BGA_LOADMODE_ARG=--load-mode none"

set "BGA_MCACHE_ARG="

if %GPU_MOE_CACHE_MIB% GTR 0 set "BGA_MCACHE_ARG=--moe-cache-mib %GPU_MOE_CACHE_MIB%"

REM 线程数在「真的上了 GPU」时改用 GPU_THREADS（物理核数 16）：SMT 争用纯属内耗。
REM 纯 CPU 退回模式在 :BGA_SMALL 就 exit /b 了，走不到这一行，仍用档位表的线程数。
set "THREADS=%GPU_THREADS%"

set "GPU_ARGS=--n-gpu-layers %BGA_N% %BGA_MOE_ARG% --parallel 1 %BGA_KVQ% %BGA_OPOFF_ARG% %BGA_LOADMODE_ARG% %BGA_MCACHE_ARG%"

REM 预算行里的视觉塔一项：走系统内存时显示「0（系统内存）」，免得用户以为漏算了。

set "BGA_MMPROJ_TXT=%BGA_MMPROJ%"

if /i "%MMPROJ_OFFLOAD%"=="host" if not "%BGA_MMPROJ_AUTOOFF%"=="1" set "BGA_MMPROJ_TXT=0（系统内存/host）"

set "GPU_BUDGET=显存 %GPU_TOTAL_MIB% MiB - 其它程序 %GPU_OTHER_MIB% - 计算/上下文 %GPU_FIXED_MIB% - 视觉塔 %BGA_MMPROJ_TXT% - KV（%BGA_KVNAME%）%BGA_KVUSED% - 安全垫 %GPU_SAFETY_MIB% → 可给权重 %BGA_AVAIL% MiB（÷%GPU_LAYER_MIB% = %BGA_N% 层），专家层上限 %BGA_ECAP%，最终余量 %BGA_SLACK% MiB"

set "GPU_BUDGET_EN=VRAM %GPU_TOTAL_MIB% - other apps %GPU_OTHER_MIB% - compute/ctx %GPU_FIXED_MIB% - mmproj %BGA_MMPROJ% - KV（%BGA_KVNAME%）%BGA_KVUSED% - headroom %GPU_SAFETY_MIB% → weights %BGA_AVAIL% MiB = %BGA_N% layers / expert cap %BGA_ECAP% / slack %BGA_SLACK% MiB"

set "GPU_STRATEGY=非专家权重上显存（%BGA_N%/%GPU_NLAYER% 层），专家上显存 %BGA_EXPERT_GPU% 层（本显存档上限 %BGA_ECAP%）+ 留内存 %BGA_NCMOE% 层，单并发槽，KV %BGA_KVNAME%"

set "GPU_STRATEGY_EN=non-expert on GPU（%BGA_N%/%GPU_NLAYER%）/ expert layers: %BGA_EXPERT_GPU% on GPU（cap %BGA_ECAP%）+ %BGA_NCMOE% in RAM / 1 slot / KV %BGA_KVNAME%"

set "GPU_CAP_NOTE="

if %BGA_ECAP% GEQ %GPU_NLAYER% goto :BGA_CAP_NOTE_DONE

set "GPU_CAP_NOTE=本机 %GPU_TOTAL_MIB% MiB 显存，专家层上显存限制为 %BGA_ECAP% 层：其余 %BGA_NCMOE% 层专家留给 CPU（%THREADS% 线程满载），GPU 专注 KV 与每 token 必读的权重 / this GPU keeps at most %BGA_ECAP% expert layer(s) on VRAM; the other %BGA_NCMOE% stay in RAM for the CPU threads"

:BGA_CAP_NOTE_DONE

REM 性能开关的状态单独一行打印：预算行已经很长，塞进去就看不清了。
set "GPU_SWITCH=加载/load %GPU_LOADMODE% · op-offload %GPU_OPOFFLOAD% · 专家缓存/moe-cache %GPU_MOE_CACHE_MIB% MiB · 线程/threads %THREADS%"

set "GPU_LOWNOTE="

if %BGA_N% GTR 31 goto :BGA_NOTE_DONE

set "GPU_LOWNOTE=层数偏少会明显影响速度：可关掉浏览器/视频等程序腾显存，或把 MMPROJ_SW 设为 off / fewer layers will slow it down: close GPU-heavy apps, or set MMPROJ_SW=off"

:BGA_NOTE_DONE

set "MMPROJ_NOTE="

if "%BGA_MMPROJ_AUTOOFF%"=="1" set "MMPROJ_NOTE=为腾出显存给权重或保住余量，本次自动不载视觉塔（省 %GPU_MMPROJ_MIB% MiB：非专家多 %BGA_MMP_GAIN% 层、专家多 %BGA_MP_E_GAIN% 层）。要处理图片请把 MMPROJ_SW 设为 on / vision tower auto-disabled to free %GPU_MMPROJ_MIB% MiB（+%BGA_MMP_GAIN% non-expert, +%BGA_MP_E_GAIN% expert layers）; set MMPROJ_SW=on to enable image input"

exit /b 0

:BGA_CALC

REM 子程序：按当前 BGA_MMPROJ 算「能上几层」。

REM 入参（已在环境里）：CTX / BGA_MMPROJ / GPU_TOTAL_MIB / GPU_OTHER_MIB /

REM   GPU_FIXED_MIB / GPU_SAFETY_MIB / GPU_LAYER_MIB / GPU_NLAYER。

REM 出参：BGA_AVAIL / BGA_N / BGA_KVQ / BGA_KVNAME / BGA_KVUSED。

set /a BGA_KVF16=%CTX% / 50

set /a BGA_KVQ8=%CTX% / 100

REM 强制 q8_0（8/12/16G 带及更低显存档）：直接按 q8 算，再不必跟 f16 比较。
REM 这是本项目的标准口径 —— 低性能设备用全精度 KV 等于白扔一半权重空间。
if defined BGA_FORCE_Q8 goto :BGA_CALC_FORCE_Q8

set "BGA_KVQ="

set "BGA_KVNAME=f16"

set /a BGA_AVAIL=%GPU_TOTAL_MIB% - %GPU_OTHER_MIB% - %GPU_FIXED_MIB% - %BGA_MMPROJ% - %BGA_KVF16% - %GPU_SAFETY_MIB%

set /a BGA_N=%BGA_AVAIL% / %GPU_LAYER_MIB%

set /a BGA_KVUSED=%BGA_KVF16%

REM 未强制 q8 的路径（仅 20G 及以上会走到）：先按 f16 算；撑不到层数上限时
REM 再试 q8_0，多出 2 层以上才值得降 KV 精度。
REM 到层数上限就收工。**注意必须先封顶再返回**：上层要用 BGA_N 比较
REM 「省下视觉塔能多上几层」，若不封顶，大显存卡上算出来的是
REM 766 与 790 这种远超上限的数，差值恒 ≥ 阈值 → 会把视觉塔误关掉。

if %BGA_N% LSS %GPU_NLAYER% goto :BGA_CALC_TRY_Q8

set /a BGA_N=%GPU_NLAYER%

exit /b 0

:BGA_CALC_FORCE_Q8

REM 强制 q8_0 支路：KV 按 CTX/100 计。算出层数后立刻封顶（理由同上）。
set /a BGA_AVAIL=%GPU_TOTAL_MIB% - %GPU_OTHER_MIB% - %GPU_FIXED_MIB% - %BGA_MMPROJ% - %BGA_KVQ8% - %GPU_SAFETY_MIB%

set /a BGA_N=%BGA_AVAIL% / %GPU_LAYER_MIB%

if %BGA_N% GTR %GPU_NLAYER% set /a BGA_N=%GPU_NLAYER%

set /a BGA_KVUSED=%BGA_KVQ8%

set "BGA_KVQ=--cache-type-k q8_0 --cache-type-v q8_0"

set "BGA_KVNAME=q8_0"

exit /b 0

:BGA_CALC_TRY_Q8

REM 还没到层数上限 —— 再算一遍 q8_0（KV 减半）。小显存卡上这通常能多装 8 层左右，

REM 而代价只有约 0.7% 速度，所以只要多出 2 层以上就换 q8_0；只多 1 层不值得降 KV 精度。

set /a BGA_AVAIL2=%GPU_TOTAL_MIB% - %GPU_OTHER_MIB% - %GPU_FIXED_MIB% - %BGA_MMPROJ% - %BGA_KVQ8% - %GPU_SAFETY_MIB%

set /a BGA_N2=%BGA_AVAIL2% / %GPU_LAYER_MIB%

if %BGA_N2% GTR %GPU_NLAYER% set /a BGA_N2=%GPU_NLAYER%

set /a BGA_GAIN=%BGA_N2% - %BGA_N%

if %BGA_GAIN% LSS 2 exit /b 0

set /a BGA_AVAIL=%BGA_AVAIL2%

set /a BGA_N=%BGA_N2%

set /a BGA_KVUSED=%BGA_KVQ8%

set "BGA_KVQ=--cache-type-k q8_0 --cache-type-v q8_0"

set "BGA_KVNAME=q8_0"

exit /b 0

:BGA_MOE_CALC

REM 子程序：用「可给权重」里没被非专家用掉的部分，推导能把几层专家放上显存。

REM 入参（环境里）：BGA_N / BGA_AVAIL / GPU_LAYER_MIB / GPU_EXPERT_LAYER_MIB / GPU_NLAYER / BGA_ECAP。

REM 出参：BGA_EXPERT_GPU（上显存的专家层数）/ BGA_NCMOE（留内存的专家层数 = --n-cpu-moe 的值）/

REM       BGA_SLACK（把专家也算进去之后真正剩下的余量，MiB）。

REM 只有非专家权重已压满 GPU_NLAYER 层时才可能有余量给专家；否则专家全留 CPU。

REM 关键：算出来的 E 还要再受 BGA_ECAP 封顶（8G 最多 1 层 / 12G 2 层 / 16G 3 层）。

if not defined BGA_ECAP set /a BGA_ECAP=%GPU_NLAYER%

set /a BGA_EXPERT_GPU=0

set /a BGA_NCMOE=%GPU_NLAYER%

if %BGA_N% LSS %GPU_NLAYER% goto :BGA_MOE_SLACK

set /a BGA_WUSED=%BGA_N% * %GPU_LAYER_MIB%

set /a BGA_LEFT=%BGA_AVAIL% - %BGA_WUSED%

REM 专家显存缓存（--moe-cache-mib）同样占专用显存，必须先扣掉再算能放几层专家，
REM 否则算出来的层数会把缓存挤到显存外。本项目默认 0（实测负收益），保留这条是为了
REM 有人手工打开它时预算不会算歪。
if %GPU_MOE_CACHE_MIB% GTR 0 set /a BGA_LEFT=%BGA_LEFT% - %GPU_MOE_CACHE_MIB%

if %BGA_LEFT% LSS %GPU_EXPERT_LAYER_MIB% goto :BGA_MOE_SLACK

set /a BGA_EXPERT_GPU=%BGA_LEFT% / %GPU_EXPERT_LAYER_MIB%

if %BGA_EXPERT_GPU% GTR %GPU_NLAYER% set /a BGA_EXPERT_GPU=%GPU_NLAYER%

if %BGA_EXPERT_GPU% GTR %BGA_ECAP% set /a BGA_EXPERT_GPU=%BGA_ECAP%

REM 放完专家层后仍必须留够 GPU_SLACK_MIN_MIB，否则就是贴顶 —— 贴顶会触发 WDDM
REM 静默分页，prefill 直接崩（2026-10-22 在 8 GB 卡上实测 200 多 → 8.4 t/s）。
REM 余量不够就少放一层，宁可用 CPU 也不能越界。
set /a BGA_SLACK_AFTER=%BGA_LEFT% - %BGA_EXPERT_GPU% * %GPU_EXPERT_LAYER_MIB%

if %BGA_SLACK_AFTER% GEQ %GPU_SLACK_MIN_MIB% goto :BGA_MOE_SET

set /a BGA_EXPERT_GPU=%BGA_EXPERT_GPU% - 1

if %BGA_EXPERT_GPU% LSS 0 set /a BGA_EXPERT_GPU=0

:BGA_MOE_SET

set /a BGA_NCMOE=%GPU_NLAYER% - %BGA_EXPERT_GPU%

if %BGA_NCMOE% LSS 0 set /a BGA_NCMOE=0

:BGA_MOE_SLACK

REM 早退路径（层数不足 / 非专家没压满）也要给 BGA_MCACHE 赋值，否则后面
REM set /a 里引用空变量会按 0 静默算错；这里统一取常量。
set /a BGA_MCACHE=%GPU_MOE_CACHE_MIB%

if not defined BGA_MCACHE set /a BGA_MCACHE=0

set /a BGA_SLACK=%BGA_AVAIL% - %BGA_N% * %GPU_LAYER_MIB% - %BGA_EXPERT_GPU% * %GPU_EXPERT_LAYER_MIB% - %BGA_MCACHE%

exit /b 0

:BGA_SMALL

REM 两种退回纯 CPU 的原因要分开说，否则用户会被引到错误的方向：
REM   1) 本档位上下文太大，KV 把显存吃到只剩几层权重 -> 该换更小的档位；
REM   2) 空闲显存本身就不够门槛 -> 该关掉占显存的程序，或本机不适合用 GPU。
if defined BGA_LOW_LAYERS goto :BGA_SMALL_LOW

set "GPU_STRATEGY=纯 CPU（空闲显存 %GPU_FREE_MIB% MiB，不足门槛 %GPU_MIN_FREE_MIB% MiB）"

set "GPU_STRATEGY_EN=CPU only - free VRAM %GPU_FREE_MIB% MiB is below the threshold %GPU_MIN_FREE_MIB% MiB"

exit /b 0

:BGA_SMALL_LOW

set "GPU_STRATEGY=纯 CPU（本档位上下文所需的 KV 把显存占满，只剩 %BGA_N% 层权重可放，不足 8 层，GPU 加速无收益；请改选更小的档位）"

set "GPU_STRATEGY_EN=CPU only - this tier's KV leaves room for only %BGA_N% layers (below 8), so GPU offload would not pay off; pick a smaller tier"

exit /b 0



:BGA_MANUAL

REM ---------- manual ----------

set "GPU_ARGS="

if defined GPU_DEVICE call :CHECK_GPU_DEVICE

if defined GPU_DEVICE set "GPU_ARGS=--device %GPU_DEVICE%"

if defined GPU_LAYERS set "GPU_ARGS=%GPU_ARGS% --n-gpu-layers %GPU_LAYERS%"

if not defined GPU_LAYERS set "GPU_ARGS=%GPU_ARGS% --n-gpu-layers 0"

if /i "%CPU_MOE%"=="all" set "GPU_ARGS=%GPU_ARGS% --cpu-moe"

if defined CPU_MOE if /i not "%CPU_MOE%"=="all" set "GPU_ARGS=%GPU_ARGS% --n-cpu-moe %CPU_MOE%"

if defined MOE_CACHE_MIB set "GPU_ARGS=%GPU_ARGS% --moe-cache-mib %MOE_CACHE_MIB%"

if /i "%KV_OFFLOAD%"=="off" set "GPU_ARGS=%GPU_ARGS% -nkvo"

if /i "%KV_OFFLOAD%"=="on" set "GPU_ARGS=%GPU_ARGS% -kvo"

set "GPU_STRATEGY=手动指定"

exit /b 0



REM ============================================================

REM  子程序：核对手工指定的 --device

REM  llama-server 对写错的设备名是「直接报错退出」，服务根本起不来，

REM  所以在拼参数之前先跟后端列出的设备名核对一次，对不上就退回自动选择。

REM ============================================================

:CHECK_GPU_DEVICE

set "DEVOK="

for %%d in (%GPU_DEV_IDS%) do if /i "%%d"=="%GPU_DEVICE%" set "DEVOK=1"

if defined DEVOK exit /b 0

echo.

echo   [警告/WARN] GPU_DEVICE=%GPU_DEVICE% 不在后端列出的设备里 / not among the devices the backend lists

echo          后端探测到/backend found：%GPU_DEV_IDS%

echo          若照此启动，llama-server 会因 invalid device 直接退出 / would exit with invalid device，

echo          已改为自动选择设备 / falling back to automatic device selection.

set "GPU_DEVICE="

exit /b 0



REM ============================================================

REM  子程序：启动前显示 GPU 计划（GPU_MODE=off 时什么都不显示）

REM ============================================================

:SHOW_GPU_PLAN

if /i "%GPU_MODE%"=="off" exit /b 0

REM 注意：这里全部用「单行 if」而不是 if ( ) 块 —— 策略/预算这些文本由变量拼成，

REM 值里可能带半角括号；块内的 %VAR% 一旦展开出 ) 会提前闭合 if 块，

REM 实测报错「此时不应有 experts」。块外展开时括号只是普通字符。

echo   GPU 策略/STRATEGY   %GPU_STRATEGY%

if defined GPU_STRATEGY_EN echo              %GPU_STRATEGY_EN%

if defined GPU_BUDGET echo   显存预算/BUDGET   %GPU_BUDGET%

if defined GPU_BUDGET_EN echo              %GPU_BUDGET_EN%

if defined GPU_SWITCH echo   性能开关/SWITCH   %GPU_SWITCH%

if defined GPU_OTHER_NOTE echo   ^[注意/NOTE^]     %GPU_OTHER_NOTE%

if defined GPU_CAP_NOTE echo   ^[注意/NOTE^]     %GPU_CAP_NOTE%

if defined MMPROJ_NOTE echo   ^[注意/NOTE^]     %MMPROJ_NOTE%

if defined GPU_LOWNOTE echo   ^[注意/NOTE^]     %GPU_LOWNOTE%

if "%GPU_AVAILABLE%"=="1" echo   GPU 设备/DEVICE     %GPU_NAME%  ^(%GPU_TOTAL_MIB% MiB 总/total / %GPU_FREE_MIB% MiB 空闲/free^)

if not "%GPU_AVAILABLE%"=="1" echo              %GPU_PROBE_NOTE%

exit /b 0



REM ============================================================

REM  子程序：从服务日志里读出「实际生效」的层分配

REM  需要外部先设置 GPU_LOG_STAMP（= 日志文件名里的时间戳）

REM  llama.cpp 会打印：

REM    load_tensors: offloaded 41/41 layers to GPU

REM ============================================================

:SHOW_GPU_ACTUAL

REM GPU_REQ / GPU_ARGS 由调用方设置：启动路径 = GPU_MODE / 本次参数，

REM status 与运行中菜单 = 记录下来的 CUR_GPU / CUR_GPU_ARGS。

REM 旧状态文件没有这些字段时为空，按 off 处理（不显示这行，与旧版输出一致）。

if "%GPU_LOG_STAMP%"=="" exit /b 0

set "GLOG=%LOG_DIR%\server-%GPU_LOG_STAMP%.log"

if not exist "%GLOG%" exit /b 0

set "GCLAUSE="

for /f "usebackq delims=" %%a in (`findstr /c:"load_tensors: offloaded" "%GLOG%"`) do set "GCLAUSE=%%a"

if defined GCLAUSE goto :SGA_SHOW

REM 取不到实际行是正常的：llama-server 在默认详细度下根本不打印层分配

REM （load_tensors: offloaded 只在 -lv 4 才输出，已实测），

REM 所以回落到启动时记录下来的实际参数。

if not defined GPU_REQ exit /b 0

if /i "%GPU_REQ%"=="off" exit /b 0

if not defined GPU_ARGS goto :SGA_NONE

if /i "%GPU_ARGS%"=="--n-gpu-layers 0" goto :SGA_NONE

echo   GPU 参数/ARGS       %GPU_ARGS%

exit /b 0

:SGA_NONE

echo   GPU 未生效，本次为纯 CPU 运行 / GPU not active, running CPU-only（原因见 环境检查_EnvCheck.bat 第 11 项 / see item 11）

exit /b 0

:SGA_SHOW

set "GCLAUSE=%GCLAUSE:*load_tensors: =%"

echo   GPU 层分配/LAYERS %GCLAUSE%

exit /b 0



REM ============================================================

REM  子程序：环境与安全检查

REM ============================================================

:SAFETY_CHECK

set "CHK_FAIL=0"

set "CHK_N=0"



call :CHK_NEXT

echo [1/10] 可执行程序 / Executables

call :CHK_FILE "%SERVER_EXE%"

call :CHK_FILE "%BIN_DIR%\llama-cli.exe"



call :CHK_NEXT

echo [2/10] 依赖动态库 / Runtime DLLs

call :CHK_FILE "%BIN_DIR%\llama.dll"

call :CHK_FILE "%BIN_DIR%\llama-common.dll"

call :CHK_FILE "%BIN_DIR%\ggml.dll"

call :CHK_FILE "%BIN_DIR%\ggml-base.dll"

echo         运行库 / runtime（随包附带 / bundled，目标机无需安装 / no VC++ Redist needed）

call :CHK_FILE "%BIN_DIR%\vcruntime140.dll"

call :CHK_FILE "%BIN_DIR%\msvcp140.dll"

call :CHK_FILE "%BIN_DIR%\vcomp140.dll"



call :CHK_NEXT

echo [3/10] CPU 指令集后端 / CPU ISA backend（AVX-512 关键 / critical）

call :CHK_FILE "%BIN_DIR%\ggml-cpu-icelake.dll"

if not exist "%BIN_DIR%\ggml-cpu-icelake.dll" goto :TISA_NONE

if exist "%BIN_DIR%\ggml-cpu-cascadelake.dll" (

  echo         [修正/FIX] 发现 ggml-cpu-cascadelake.dll / found，它会抢在 icelake 前面被选中 / it would be picked before icelake，

  echo                导致 VBMI 指令失效 / disabling VBMI。正在改名为/renaming to .disabled ...

  ren "%BIN_DIR%\ggml-cpu-cascadelake.dll" "ggml-cpu-cascadelake.dll.disabled" >nul 2>nul

  if exist "%BIN_DIR%\ggml-cpu-cascadelake.dll" (

    echo         [失败/FAIL] 无法改名 / cannot rename，请手动处理 / handle it manually

    set "CHK_FAIL=1"

  ) else (

    echo         [修正完成/FIXED] 现在会命中/WILL USE icelake（AVX-512 + VNNI + VBMI）

  )

) else (

  echo         正常/OK    icelake 变体优先/preferred，AVX-512 + VNNI + VBMI 生效/active

)

goto :TISA_END

:TISA_NONE

echo         提示/HINT  icelake 变体缺失/missing，需重新编译补齐 / rebuild to add it（见上方 [失败] 项 / see the FAIL item above）

:TISA_END



call :CHK_NEXT

echo [4/10] 模型文件 / Model file

if defined MODEL_VALID (

  for %%F in ("%MODEL%") do echo         正常/OK    %%~nxF

  call :SHOW_MODEL_SIZE

) else (

  if "%MODEL_SOFT%"=="1" (

    echo         [警告/WARN]  没有可用模型 / no usable model，接下来会引导下载 / will offer to download（1=IQ3_S / 2=Q4_K_M）

  ) else (

    echo         [失败/FAIL]  缺少可用模型 / missing model：%MODEL%

    echo                 下载方法见 / see llama.cpp\models\下载模型.md

    set "CHK_FAIL=1"

  )

)



call :CHK_NEXT

echo [5/10] 视觉投影 / Vision projector（多模态/multimodal）

if exist "%MMPROJ%" (

  echo         正常/OK    mmproj-BF16.gguf

) else (

  echo         [警告/WARN]  未找到 mmproj / not found，将以纯文本模式启动 / text-only mode（不处理图片 / images disabled）

)



call :CHK_NEXT

echo [6/10] 端口/Port %PORT% 占用 / in use?

call :PORT_BUSY

if "%PORT_STATE%"=="busy" (

  echo         [失败/FAIL]  端口已被进程占用 / port held by PID %PORT_PID%，本次启动会失败 / startup would fail

  for /f "usebackq delims=" %%a in (`powershell -NoProfile -Command "(Get-Process -Id %PORT_PID% -ErrorAction SilentlyContinue).ProcessName"`) do echo                 占用者/holder：%%a

  set "CHK_FAIL=1"

) else (

  echo         正常/OK    端口空闲 / port free

)



call :CHK_NEXT

echo [7/10] 磁盘剩余空间 / Free disk space

set "DL=%ROOT:~0,1%"

for /f "usebackq delims=" %%a in (`powershell -NoProfile -Command "[int]((Get-PSDrive -Name '%DL%').Free/1GB)"`) do set "DISK_GB=%%a"

if %DISK_GB% LSS 2 (

  echo         [失败/FAIL]  %DL%: 盘仅剩/only %DISK_GB% GB，无法写日志 / cannot write logs

  set "CHK_FAIL=1"

) else (

  echo         正常/OK    %DL%: 盘剩余/free %DISK_GB% GB

)



call :CHK_NEXT

echo [8/10] 重复实例 / Duplicate instance

call :DETECT

if defined SRV_PID (

  echo         [失败/FAIL]  已有 llama-server 在运行 / already running（PID %SRV_PID%），不能重复启动 / do not start twice

  set "CHK_FAIL=1"

) else (

  echo         正常/OK    无残留实例 / no stale instance

)

call :CLEAN_STALE_PID



call :CHK_NEXT

echo [9/10] 访问密钥与局域网 / API key and LAN

call :ENSURE_KEY

if exist "%KEY_FILE%" (

  call :LOAD_KEY

  if defined API_KEY (

    echo         正常/OK    访问密钥已就绪 / API key ready（%KEY_FILE%）

  ) else (

    echo         [失败/FAIL]  密钥文件里没有有效密钥 / no valid key in the key file

    set "CHK_FAIL=1"

  )

) else (

  echo         [失败/FAIL]  无法创建密钥文件 / cannot create key file %KEY_FILE%

  set "CHK_FAIL=1"

)

call :GET_LAN_IP

if defined LAN_IP (

  echo         提示/HINT    局域网入口/LAN URL http://%LAN_IP%:%PORT%  ^(需带密钥/key required^)

) else (

  echo         [警告/WARN]  未检测到局域网 IPv4 / no LAN IPv4，其它设备可能无法访问 / other devices may not connect

)



call :CHK_NEXT

echo [10/10] 显卡 / GPU（NVIDIA 独显混合卸载 / hybrid offload）

REM 这一项只报「能不能用」，永远不设 [失败] —— GPU 不可用时服务照样能

REM 以纯 CPU 跑起来，不该因为显卡的事把启动拦掉。

REM 默认 GPU_MODE=auto，正常都走 :TGPU_REQ 去探测；能落到下面两条的，

REM 只可能是手动关了（命令行 nogpu，或把顶部 GPU_MODE 改成 off）。

if /i not "%GPU_MODE%"=="off" goto :TGPU_REQ

if not exist "%BIN_DIR%\ggml-cuda.dll" goto :TGPU_PLAIN

echo         提示/HINT    已关闭 GPU / GPU off（GPU_MODE=off），本次按纯 CPU 运行 / running CPU-only

echo                 想启用/to enable：启动大模型_StartModel.bat start 2 gpu   或把顶部 GPU_MODE 改成 auto / or set GPU_MODE=auto

goto :TGPU_END

:TGPU_PLAIN

echo         提示/HINT    已关闭 GPU / GPU off（GPU_MODE=off），本次按纯 CPU 运行 / running CPU-only

echo                 有 N 卡想加速 / have an NVIDIA card? 跑 环境检查_EnvCheck.bat 看第 11 项 / see item 11

goto :TGPU_END

:TGPU_REQ

call :GPU_PROBE

if "%GPU_AVAILABLE%"=="1" (

  echo         正常/OK    %GPU_NAME%

  echo                 显存/VRAM %GPU_TOTAL_MIB% MiB 总/total / %GPU_FREE_MIB% MiB 空闲/free，本次将启用 GPU 混合卸载 / hybrid offload will be enabled

) else (

  echo         提示/HINT    未启用 GPU / GPU not used，本次按纯 CPU 运行 / CPU-only（默认兜底 / default fallback，不是错误 / not an error）

  echo                 %GPU_PROBE_NOTE%

  echo                 排查/to diagnose：跑 环境检查_EnvCheck.bat 看第 11 项 / see item 11

)

:TGPU_END

exit /b 0



:CHK_NEXT

exit /b 0



:CHK_FILE

if exist "%~1" (

  echo         正常/OK    %~nx1

) else (

  echo         [失败/FAIL]  缺少/missing %~1

  set "CHK_FAIL=1"

)

exit /b 0



:CLEAN_STALE_PID

if exist "%PID_FILE%" (

  call :DETECT

  if not defined SRV_PID (

    echo         [清理/CLEAN] 删除残留的状态文件 / removing stale state file（服务并不在运行 / service is not running）

    del "%PID_FILE%" >nul 2>nul

  )

)

exit /b 0



REM ============================================================

REM  子程序：内存安全检查

REM ============================================================

:NEED_FOR_CTX
REM 入参：%~1 = 上下文大小；出参：NEED_GB（总内存需求，GiB，向上取整）
REM 口径：模型大小 + KV（每 64K 上下文约 1 GiB）+ 2 GiB（系统与计算缓冲）
REM 自检：IQ3_S 12.7 GiB + 64K = 13 + 1 + 2 = 16 GiB，正好对上实测口径
REM       「16G 内存 + 4G 以上显存可以跑到 64K」。
set "NFC_MB=%MODEL_MB%"
if not defined NFC_MB set "NFC_MB=21504"
set /a NFC_MODEL=(NFC_MB + 1023) / 1024
set /a NFC_KV=(%~1 + 65535) / 65536
set /a NEED_GB=NFC_MODEL + NFC_KV + 2
REM --load-mode none 是「全量读进私有内存」，不跟 page cache 共享：mmap 时模型页可以
REM 被系统随时回收，常驻时不行。所以内存口径要加 1 GiB，否则 32 GB 机器上 128K 档会被放行到换页。
if /i "%GPU_LOADMODE%"=="none" set /a NEED_GB=%NEED_GB% + 1
exit /b 0
:MEM_CHECK
set "MEM_BLOCK=0"
set "MEM_WARN=0"
set "MEM_FAIL_WHY="
REM 可用内存与总内存一次问完：每次外部调用冷启动要 0.2~0.4 s，能省就省。
set "MEM_RAW="
for /f "usebackq delims=" %%a in (`powershell -NoProfile -Command "$f=[int]((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory/1024); $t=[int]((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory/1MB); 'F'+$f+' T'+$t"`) do set "MEM_RAW=%%a"
if not defined MEM_RAW goto :MEMC_PARSE_FAIL
if not "%MEM_RAW:~0,1%"=="F" goto :MEMC_PARSE_FAIL
REM 两个字段各带一个字母前缀（F…/T…），都要去掉 —— 漏掉一个的话
REM set /a 会把 "T62444" 当成变量名（未定义=0），总内存被算成 0，
REM 于是「总内存不足」误判，还会和输入耗尽叠加成死循环。
for /f "tokens=1,2" %%a in ("%MEM_RAW%") do set "FREE_RAW=%%a"
for /f "tokens=1,2" %%a in ("%MEM_RAW%") do set "TOTAL_RAW=%%b"
set "FREE_MB=%FREE_RAW:~1%"
set "TOTAL_MB=%TOTAL_RAW:~1%"
if not defined FREE_MB goto :MEMC_PARSE_FAIL
if not defined TOTAL_MB goto :MEMC_PARSE_FAIL
goto :MEMC_OK
:MEMC_PARSE_FAIL
REM 读不到就当作「不知道」，不拦启动：宁可让用户跑起来，也不要因为探测失败卡住。
set "FREE_MB=0"
set "TOTAL_MB=0"
:MEMC_OK
set /a FREE_GB=%FREE_MB% / 1024
set /a TOTAL_GB=%TOTAL_MB% / 1024
call :NEED_FOR_CTX %CTX%
set /a NEED_MB=%NEED_GB% * 1024
set /a HALF_MB=%NEED_MB% / 2
echo.
echo   内存检查/MEMORY：总内存/total %TOTAL_GB% GB，当前可用/free %FREE_GB% GB，本档位+本模型需要约/needs ~%NEED_GB% GB
REM 判定口径（2026-10-16 改）：
REM   1. 总内存 < 需求        -> 失败（机器规格本身不够；换更小档位或更小量化）
REM   2. 可用内存 < 需求的一半 -> 失败（现在被别的程序吃掉太多，必然大量换页）
REM   3. 可用内存 < 需求       -> 警告（可以继续，但可能变慢）
REM 为什么硬门槛看「总内存」：档位表上的 16G/32G 说的就是机器总内存，
REM   而且模型是 mmap 的、不必一次性全驻留；只看可用内存会把 16G 机器误杀。
REM   探测失败（TOTAL_MB=0）时跳过内存判定，不阻断启动。
if %TOTAL_MB% GTR 0 if %TOTAL_GB% LSS %NEED_GB% set "MEM_BLOCK=1"
if %TOTAL_MB% GTR 0 if %TOTAL_GB% LSS %NEED_GB% set "MEM_FAIL_WHY=total"
if %TOTAL_MB% GTR 0 if %FREE_MB% LSS %HALF_MB% set "MEM_BLOCK=1"
if %TOTAL_MB% GTR 0 if %FREE_MB% LSS %HALF_MB% set "MEM_FAIL_WHY=free"
if %TOTAL_MB% GTR 0 if not "%MEM_BLOCK%"=="1" if %FREE_MB% LSS %NEED_MB% set "MEM_WARN=1"
if "%MEM_BLOCK%"=="1" if "%MEM_FAIL_WHY%"=="total" echo   [失败/FAIL]  总内存低于本档位与模型的需求 / total RAM below what this tier and model need
if "%MEM_BLOCK%"=="1" if "%MEM_FAIL_WHY%"=="free" echo   [失败/FAIL]  可用内存不足需求的一半，启动会大量换页 / free RAM under half of the requirement
if "%MEM_BLOCK%"=="0" if "%MEM_WARN%"=="1" echo   [警告/WARN]  可用内存低于需求，建议先关掉占内存的程序 / free RAM below the requirement, close memory-hungry apps first
if "%MEM_BLOCK%"=="0" if "%MEM_WARN%"=="0" if %TOTAL_MB% GTR 0 echo   正常/OK    内存充足 / plenty of RAM
if "%MEM_BLOCK%"=="0" if %TOTAL_MB%==0 echo   正常/OK    内存探测未返回，跳过内存判定 / memory probe returned nothing, check skipped
exit /b 0


:ASK_MEM_CONTINUE

set "ASK_RC=0"

set "YN="

set /p "YN=  仍要继续启动吗？/ Continue anyway? (y/N) : "

set "YN=%YN:~0,1%"

if /i "%YN%"=="y" set "ASK_RC=1"

exit /b 0


REM ============================================================

REM  子程序：等待按键（静默模式下直接跳过）

REM ============================================================

:PAUSE_IF

if "%QUIET%"=="1" exit /b 0

pause

exit /b 0

