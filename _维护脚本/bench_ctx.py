"""
llama.cpp 本机 CPU 推理 —— 上下文 × 线程 组合基准（以生成速度 t/s 为核心指标）
用法: python bench_ctx.py <ctx大小> <期望生成token数> <线程数> <server日志路径>

- 把上下文填满到 (ctx - 期望生成数 - 安全余量)，模拟该档位下的中长对话
- 关闭思考链，让 token 全部用于实际回答
- 从 llama-server 日志中读取权威的 prompt eval / eval 计时
- 输出一行 CSV: ctx,threads,pp_tokens,pp_tps,gen_tokens,gen_tps,wall_s
"""
import json
import os
import re
import sys
import time
import io
import urllib.request

def _load_api_key():
    """从工作区根目录 api-key.txt 读取密钥（跳过注释行），没有就返回空串。"""
    import os
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "api-key.txt")
    try:
        with io.open(p, encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    return line
    except OSError:
        pass
    return ""


API_KEY = _load_api_key()

HOST = "http://127.0.0.1:35035"
for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
    os.environ.pop(k, None)
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

PARA = (
    "第{i}节 本地推理工程记录：在纯中央处理器环境下部署大语言模型，"
    "需要同时权衡模型体积、量化精度与内存带宽三者之间的关系。"
    "量化把权重从十六位浮点压缩到四位整数，显著降低了内存占用和带宽压力，"
    "线程调度方面，物理核心的利用率比逻辑线程数更值得关注，"
    "因为同步开销与内存带宽争用会在高并发时抵消并行收益。"
)

# 要求生成较长正文，便于稳定测量生成速度
QUESTION = (
    "\n\n以上内容为背景资料。请围绕「在纯CPU环境下部署大语言模型」写一篇约三百字的说明，"
    "要求分三点展开：内存带宽、线程配置、量化选择。直接开始写正文，不要复述题目。"
)

RE_PP = re.compile(r"prompt eval time\s*=\s*([\d.]+) ms /\s*(\d+) tokens \(.*?([\d.]+) tokens per second")
RE_TG = re.compile(r"(?<!prompt )eval time\s*=\s*([\d.]+) ms /\s*(\d+) tokens \(.*?([\d.]+) tokens per second")


def post(path, payload, timeout=7200):
    req = urllib.request.Request(
        HOST + path,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 **( {"Authorization": "Bearer " + API_KEY} if API_KEY else {} )},
    )
    with opener.open(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def tokenize(text):
    return len(post("/tokenize", {"content": text})["tokens"])


def last_timings(log_path):
    pp = tg = None
    try:
        with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                m = RE_PP.search(line)
                if m:
                    pp = (float(m.group(2)), float(m.group(3)))
                m = RE_TG.search(line)
                if m:
                    tg = (float(m.group(2)), float(m.group(3)))
    except FileNotFoundError:
        pass
    return pp, tg


def main():
    ctx = int(sys.argv[1])
    gen_want = int(sys.argv[2])
    threads = sys.argv[3]
    log_path = sys.argv[4] if len(sys.argv) > 4 else "/e/llm-cpp/srv_matrix.log"

    # 固定预留 1024 token 给生成，保证每一档都有相同的生成空间
    gen_room = 1024
    prompt_budget = ctx - gen_room

    # 先按估算累加，再用真实 tokenize 迭代裁剪（数字编号会占额外 token，估算必偏小）
    unit = tokenize(PARA.format(i=1))
    parts, got, i = [], 0, 0
    while got < prompt_budget:
        i += 1
        parts.append(PARA.format(i=i))
        got += unit

    prompt = "".join(parts) + QUESTION
    for _ in range(8):
        n = tokenize(prompt)
        if n <= prompt_budget:
            break
        drop = max(1, int((n - prompt_budget) / unit) + 1)
        parts = parts[:len(parts) - drop]
        prompt = "".join(parts) + QUESTION

    t0 = time.time()
    r = post("/v1/chat/completions", {
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": gen_want,
        "temperature": 0.7,
        "chat_template_kwargs": {"enable_thinking": False},
    })
    wall = time.time() - t0

    usage = r.get("usage", {})
    pp_tok = usage.get("prompt_tokens")
    tg_tok = usage.get("completion_tokens")
    pp_tps, tg_tps = None, None
    for _ in range(20):
        p, t = last_timings(log_path)
        if p and t:
            pp_tok, pp_tps = p
            tg_tok, tg_tps = t
            if (tg_tok or 0) > 8:
                break
        time.sleep(1)

    print(f"{ctx},{threads},{pp_tok},{pp_tps:.2f},{tg_tok},{tg_tps:.2f},{wall:.1f}", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR,{type(e).__name__}:{e}")
        sys.exit(1)
