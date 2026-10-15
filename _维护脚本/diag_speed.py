# -*- coding: utf-8 -*-
"""一键诊断：测量当前服务的生成速度，并抓取当时的机器状态。

用途：怀疑「变慢了 / 只有 8~9 t/s」时跑一次，把结果贴出来即可定位原因。

用法：
    python _维护脚本\\diag_speed.py            # 默认测 短提示 + 约 8K 长提示
    python _维护脚本\\diag_speed.py --full     # 额外测约 16K 长提示（更慢，约 3 分钟）

判读要点（正常基线，GTX 1060 3GB / 32K 档）：
    短提示生成 ≈ 21~23 t/s ；8K 提示 prefill ≈ 130~170 t/s
    若生成明显偏低（例如 8 t/s），看脚本输出的「机器状态」一节：
      - llama 专用显存 + 共享显存 = 总需求，若远超显卡容量 → 显存超额（WDDM 分页）
      - % Processor Performance 明显低于 100 → CPU 被限频（电源计划 / 第三方工具）
      - GPU 占用高但功耗低、显存带宽占用低 → GPU 在等 CPU（CPU 侧瓶颈）
      - 其它进程占用大 → 就是它们在抢资源
"""
import argparse
import ctypes
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PORT = 35035
BASE = "http://127.0.0.1:%d" % PORT


def read_key():
    path = os.path.join(ROOT, "api-key.txt")
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            s = line.strip()
            if s and not s.startswith("#"):
                return s
    return None


def http_json(path, payload=None, timeout=900, key=None):
    req = urllib.request.Request(BASE + path)
    if key:
        req.add_header("Authorization", "Bearer " + key)
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        req.data = data
        req.add_header("Content-Type", "application/json")
    req.method = "POST" if payload is not None else "GET"
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def make_prompt(chars, tag):
    """构造带唯一标记的长提示（避免命中服务端 KV 前缀缓存）。"""
    unit = "【%s-%d】内存带宽指处理器与主存之间每秒可传输的数据量；解码阶段每个 token 只激活少量专家，却要把权重从主存搬入缓存，瓶颈落在带宽而非算力。" % (tag, 0)
    unit = unit.replace("-0", "-%d")
    body = "".join(unit % i for i in range(chars // 70 + 1))
    return "请阅读材料后一句话概括。\n\n" + body + "\n\n概括："


def measure(label, prompt, key, max_tokens=120):
    print("\n--- %s ---" % label)
    t0 = time.time()
    try:
        d = http_json("/v1/chat/completions",
                      {"messages": [{"role": "user", "content": prompt}], "max_tokens": max_tokens},
                      key=key)
    except urllib.error.HTTPError as e:
        print("  请求失败 %s: %s" % (e.code, e.read().decode("utf-8", "replace")[:200]))
        return None
    except Exception as e:
        print("  请求异常: %s" % e)
        return None
    t = d.get("timings") or {}
    print("  提示 %s token | prefill %.1f t/s" % (t.get("prompt_n"), t.get("prompt_per_second", 0)))
    print("  生成 %s token | **%.2f t/s**（用时 %.1fs）"
          % (t.get("predicted_n"), t.get("predicted_per_second", 0), time.time() - t0))
    return t.get("predicted_per_second", 0)


def ps(cmd):
    """调用 PowerShell（避免从 bash 直接调，安全策略会拦）。"""
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", cmd],
                             capture_output=True, timeout=60)
        return out.stdout.decode("gbk", "replace").strip()
    except Exception as e:
        return "(取不到: %s)" % e


def machine_state():
    print("\n=== 机器状态 ===")
    print("电源计划 :", ps("(powercfg /getactivescheme) -replace '.*\\((.*)\\).*','$1'")
          or ps("powercfg /getactivescheme"))
    print("CPU 有效性能 :", ps("$c=Get-Counter '\\Processor Information(_Total)\\% Processor Performance' -MaxSamples 1; "
                            "[math]::Round($c.CounterSamples[0].CookedValue)"), "%  （<100 表示被限频）")
    print("内存 :", ps("$o=Get-CimInstance Win32_OperatingSystem; "
                     "'总 {0:N1} GB / 可用 {1:N1} GB' -f ($o.TotalVisibleMemorySize/1MB), ($o.FreePhysicalMemory/1MB)"))
    print("内存分页 :", ps("(Get-Counter '\\Memory\\Pages/sec' -MaxSamples 1).CounterSamples[0].CookedValue"),
          "页/秒  （持续 > 数百说明在换页，模型被挤出内存）")
    print("GPU :", ps("nvidia-smi --query-gpu=name,utilization.gpu,utilization.memory,power.draw,clocks.sm,clocks.mem,memory.used,memory.total --format=csv,noheader")
          or "(无 nvidia-smi)")
    print("llama 显存 :", ps(
        "$lp=(Get-CimInstance Win32_Process -Filter \"Name='llama-server.exe'\").ProcessId;"
        "if($lp){$d=(Get-Counter '\\GPU Process Memory(pid_*)\\Dedicated Usage' -MaxSamples 1).CounterSamples|?{$_.InstanceName -like \"pid_${lp}_*\"}|select -First 1;"
        "$s=(Get-Counter '\\GPU Process Memory(pid_*)\\Shared Usage' -MaxSamples 1).CounterSamples|?{$_.InstanceName -like \"pid_${lp}_*\"}|select -First 1;"
        "'专用 {0:N0} MB + 共享(系统内存) {1:N0} MB' -f ($d.CookedValue/1MB), ($s.CookedValue/1MB)} else {'(服务未运行)'}"))
    print("\nCPU 占用前 8 名（区别于 llama-server 的其它负载）:")
    print(ps("Get-Process | ?{$_.Name -ne 'llama-server'} | Sort-Object CPU -Descending | "
             "Select-Object -First 8 @{n='进程';e={$_.Name}},Id,@{n='CPU秒';e={[math]::Round($_.CPU)}},"
             "@{n='内存GB';e={[math]::Round($_.WorkingSet64/1GB,1)}} | Format-Table -AutoSize | Out-String -Width 100"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true", help="额外测约 16K 长提示")
    args = ap.parse_args()

    key = read_key()
    if not key:
        sys.exit("未找到 api-key.txt")
    try:
        http_json("/health", key=key, timeout=6)
        print("服务在线：%s" % BASE)
    except Exception as e:
        sys.exit("服务未运行或无法访问（%s）。先双击 启动大模型.bat 启动。" % e)

    short = measure("短提示（约 30 token，最能反映纯生成速度）", "用中文写一段 200 字的短文，谈谈阅读的价值。", key)
    mid = measure("约 8K 提示（长上下文下的 prefill 与生成）", make_prompt(20000, "mid"), key)
    full = measure("约 16K 提示", make_prompt(30000, "full"), key) if args.full else None

    machine_state()

    print("\n=== 结论 ===")
    vals = [v for v in (short, mid, full) if v]
    if not vals:
        print("  未取得有效测量。")
    elif short and short < 15:
        print("  生成速度明显偏低（短提示 %.2f t/s，正常应 21~23）。" % short)
        print("  对照上面「机器状态」：重点是 CPU 有效性能、内存分页、其它进程占用、")
        print("  以及 llama 显存是否远超显卡容量。把这整段输出贴出来即可定位。")
    else:
        print("  生成速度正常（短提示 %.2f t/s）。配置本身没有问题。" % short)
        print("  若某个客户端里感觉慢，多半是客户端注入了很长的系统提示词/工具定义，")
        print("  看 logs\\ 最新日志的 n_tokens 数值（越大 = 每次要读的提示越长）。")


if __name__ == "__main__":
    main()
