# -*- coding: utf-8 -*-
"""冒烟启动测试：用与生成器同源的 .bat 在真实 3GB 设备上拉起服务，
确认改后的脚本语法无误、能监听端口、能返回首个 token，然后关闭。
（当前设备无 8/12/16G 显存，那三档的合法性由 check_budget.py 用真实逻辑跑过。）
"""
import os, sys, time, subprocess, urllib.request, json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BAT = os.path.join(ROOT, "启动大模型_StartModel.bat")
LOGDIR = os.path.join(ROOT, "logs")
PORT = 35035
HOST = "127.0.0.1"

def run_bat(*args):
    # 与 check_budget.py 同源：subprocess 调 cmd /c，沙箱内允许
    # 必须带 quiet：否则 start 拉起服务后会卡在“是否打开网页控制台”的 set /p 等待输入
    return subprocess.run(["cmd", "/c", BAT] + list(args) + ["quiet"],
                          capture_output=True, text=True, encoding="gbk",
                          errors="replace", cwd=ROOT, timeout=90)

# 清掉上一轮可能残留的服务进程
subprocess.run(["taskkill", "/F", "/IM", "llama-server.exe"],
               capture_output=True, text=True)
time.sleep(2)

print("== 启动档位1 (nothink, quiet) ==", flush=True)
r = run_bat("start", "1", "nothink")
print("bat stdout:", r.stdout.strip()[:400])
print("bat stderr:", r.stderr.strip()[:200])

# 等待 server 日志出现 listening
ready = False
for _ in range(48):  # 最多约 8 分钟
    logs = sorted([os.path.join(LOGDIR, f) for f in os.listdir(LOGDIR)
                   if f.startswith("server-") and f.endswith(".log")],
                  key=os.path.getmtime, reverse=True)
    if logs:
        data = open(logs[0], "r", encoding="utf-8", errors="replace").read()
        if "server is listening" in data or "listening on" in data:
            ready = True
            print("== 服务已监听 (log=%s) ==" % logs[0], flush=True)
            break
    time.sleep(10)
if not ready:
    print("!! 超时未监听，尾部日志：")
    if logs:
        print(open(logs[0], "r", encoding="utf-8", errors="replace").read()[-800:])
    sys.exit(2)

# 发一个极小请求，确认能返回 token（不测速度，只测“能启动并服务”）
# 读取 api-key.txt（与 .bat 同源的密钥文件），带上鉴权头
api_key = ""
kf = os.path.join(ROOT, "api-key.txt")
if os.path.exists(kf):
    for line in open(kf, "r", encoding="utf-8", errors="replace"):
        line = line.strip()
        if line and not line.startswith("#"):
            api_key = line
            break
print("== 使用 api-key 前几位: %s... ==" % api_key[:4], flush=True)

payload = json.dumps({
    "model": "local",
    "messages": [{"role": "user", "content": "用一句话自我介绍。"}],
    "max_tokens": 24, "temperature": 0.0,
}).encode("utf-8")
hdr = {"Content-Type": "application/json"}
if api_key:
    hdr["Authorization"] = "Bearer %s" % api_key
req = urllib.request.Request(
    "http://%s:%d/v1/chat/completions" % (HOST, PORT),
    data=payload, headers=hdr)
try:
    with urllib.request.urlopen(req, timeout=120) as resp:
        out = json.loads(resp.read().decode("utf-8"))
        txt = out["choices"][0]["message"]["content"]
        print("== 首个响应(token) ==", txt[:120])
        print("SMOKE_OK")
except Exception as e:
    print("!! 请求失败:", repr(e))
    sys.exit(3)
finally:
    print("== 关闭服务 ==", flush=True)
    run_bat("stop")
    subprocess.run(["taskkill", "/F", "/IM", "llama-server.exe"],
                   capture_output=True, text=True)
    time.sleep(3)
    print("done")
