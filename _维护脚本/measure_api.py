# -*- coding: utf-8 -*-
"""对已在运行的服务做一次固定负载测量（ASCII 输出，便于日志查看）。

用法：python measure_api.py <label>
"""
import json
import subprocess
import sys
import time
import urllib.request

PORT = 35035
PROMPT = "Summarize briefly: " + ("the quick brown fox jumps over the lazy dog. " * 6)

# 服务开了密钥鉴权，必须带 Authorization 头，否则 401
KEY = ""
with open(r"E:\llm-cpp\api-key.txt", "rb") as f:
    for line in f.read().decode("utf-8", "replace").split("\n"):
        if line.strip() and not line.strip().startswith("#"):
            KEY = line.strip()
            break


def vram():
    try:
        o = subprocess.run([r"C:\Windows\System32\nvidia-smi.exe",
                            "--query-gpu=memory.used,memory.total",
                            "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=15)
        return o.stdout.strip().split("\n")[0]
    except Exception:
        return "n/a"


def run():
    body = json.dumps({"messages": [{"role": "user", "content": PROMPT}],
                       "max_tokens": 128, "stream": False}).encode()
    req = urllib.request.Request("http://127.0.0.1:%d/v1/chat/completions" % PORT,
                                 data=body,
                                 headers={"Content-Type": "application/json",
                                          "Authorization": "Bearer " + KEY})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=900) as r:
        return json.loads(r.read().decode("utf-8")), time.time() - t0


label = sys.argv[1] if len(sys.argv) > 1 else "run"
print("  [%s] VRAM before = %s" % (label, vram()))
tg, pp = [], []
for i in range(3):
    d, w = run()
    t = d["timings"]
    tg.append(t["predicted_per_second"])
    pp.append(t["prompt_per_second"])
    print("  [%s] #%d tg=%.2f t/s pp=%.1f t/s gen=%d tok wall=%.1fs"
          % (label, i + 1, t["predicted_per_second"], t["prompt_per_second"],
             t["predicted_n"], w))
print("  [%s] VRAM after  = %s" % (label, vram()))
print("  [%s] SUMMARY tg median=%.2f  pp median=%.1f  (n=%d)"
      % (label, sorted(tg)[len(tg) // 2], sorted(pp)[len(pp) // 2], len(tg)))
