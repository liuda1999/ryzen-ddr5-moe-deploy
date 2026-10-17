# -*- coding: utf-8 -*-
"""启动 8G 档服务并常驻保持，供人工手工测试。

用法：
    python _维护脚本/start_service.py 4      # 档位 4 = 96K（当前验证通过的档）
    python _维护脚本/start_service.py 3      # 档位 3 = 64K

脚本做三件事：
  1. 用项目自己的 启动大模型_StartModel.bat start <档位> 启动服务（真链路，不绕 bat）
  2. 喂入 n 跳过「是否生成新 API Key」的交互确认（保留现有密钥）
  3. 启动成功后**不退出**，一直挂在这里 —— 否则它启动的进程树会被回收，服务跟着死

关闭方式（另开窗口）：启动大模型_StartModel.bat stop
"""
import os
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BAT = os.path.join(ROOT, "启动大模型_StartModel.bat")
LOGDIR = os.path.join(ROOT, "logs")
HOST = "http://127.0.0.1:35035"
TIER = sys.argv[1] if len(sys.argv) > 1 else "4"

TIER_DESC = {
    "1": "32K", "2": "48K", "3": "64K", "4": "96K",
    "5": "128K", "6": "160K", "7": "192K",
}


def api_key():
    p = os.path.join(ROOT, "api-key.txt")
    if not os.path.exists(p):
        return ""
    for ln in open(p, "rb").read().decode("gbk", errors="replace").splitlines():
        s = ln.strip()
        if s and not s.startswith("#"):
            return s
    return ""


def health_ok():
    try:
        with urllib.request.urlopen(HOST + "/health", timeout=5) as r:
            return r.status == 200
    except Exception:
        return False


def tail_log(n=4000):
    cands = [os.path.join(LOGDIR, f) for f in os.listdir(LOGDIR)
             if f.startswith("server-") and f.endswith(".log")] if os.path.isdir(LOGDIR) else []
    if not cands:
        return ""
    latest = max(cands, key=os.path.getmtime)
    raw = open(latest, "rb").read()
    txt = raw.decode("utf-8", errors="replace")
    return txt[-n:]


def nvidia():
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total,utilization.gpu",
             "--format=csv,noheader"], capture_output=True, text=True, timeout=10)
        return out.stdout.strip()
    except Exception:
        return "?"


def main():
    os.makedirs(LOGDIR, exist_ok=True)
    logpath = os.path.join(LOGDIR, "user_run_start.txt")
    outf = open(logpath, "wb")

    print("[启动] 启动大模型_StartModel.bat start %s（档位 %s / %s）"
          % (TIER, TIER, TIER_DESC.get(TIER, "?")), flush=True)
    p = subprocess.Popen(["cmd", "/c", BAT, "start", TIER], cwd=ROOT,
                         stdin=subprocess.PIPE, stdout=outf,
                         stderr=subprocess.STDOUT)
    try:
        p.stdin.write(b"n\nn\nn\nn\n")
        p.stdin.flush()
        p.stdin.close()
    except Exception:
        pass

    t0 = time.time()
    ok = False
    while time.time() - t0 < 420:
        if health_ok():
            ok = True
            break
        time.sleep(3)

    if not ok:
        print("[失败] 420 秒内服务未就绪。bat 输出尾部：", flush=True)
        try:
            print(open(logpath, "rb").read().decode("gbk", errors="replace")[-2000:], flush=True)
        except Exception:
            pass
        print("[失败] 服务日志尾部：", flush=True)
        print(tail_log(2500), flush=True)
        return 2

    time.sleep(2)
    print("\n" + "=" * 70)
    print("服务已就绪，可以开始手动测试")
    print("=" * 70)
    print("  接口地址 : %s/v1" % HOST)
    print("  健康检查 : %s/health" % HOST)
    print("  API Key  : %s" % api_key())
    print("  模型名   : qwen3.6-35b-a3b（OpenAI 兼容，可用任意名字）")
    print("  档位     : %s（%s 上下文）" % (TIER, TIER_DESC.get(TIER, "?")))
    print("  显存     : %s" % nvidia())
    print("\n--- 服务端实际启动参数 ---")
    for ln in tail_log(60000).splitlines():
        if "n_ctx_slot" in ln or "n-gpu-layers" in ln or "--n-cpu-moe" in ln:
            print("  " + ln.strip()[:150])
    print("\n--- 关闭方式 ---")
    print("  cd E:\\llm-cpp && 启动大模型_StartModel.bat stop")
    print("  或  taskkill /IM llama-server.exe /F")
    print("\n[保持] 本进程驻留中，服务不会因脚本退出而回收。Ctrl+C 可结束（服务仍在）。", flush=True)

    # 常驻：保住进程树，服务才不会被回收
    while True:
        time.sleep(30)


if __name__ == "__main__":
    sys.exit(main())
