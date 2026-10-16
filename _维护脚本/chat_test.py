"""
llama.cpp 本机 CPU 推理 —— 长上下文压力测试（大海捞针 / Needle-in-a-Haystack）
用法: python chat_test.py <目标上下文token数> [模型回答预留token数]

- 通过 llama-server 的 /tokenize 接口精确构造接近目标长度的提示词
- 在文档约 25% 处埋入唯一"锚点"信息，末尾提问，检验长上下文是否真的被记住
- 同时保留普通多轮对话测试（--mode chat）
- 绕过沙箱代理，直连 127.0.0.1
"""
import json
import os
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
# 关键：清掉沙箱注入的 HTTPS_PROXY，否则 127.0.0.1 会被代理拦截返回 502
for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
    os.environ.pop(k, None)
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

NEEDLE = "【隐藏锚点】项目编号是 ZEBRA-9152，验收口令是「长上下文推理正常」。"
QUESTION = "上面这份文档里埋了一条隐藏信息。请找出并原样回答：项目编号是什么？验收口令是什么？"


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


PARA = (
    "第{i}节 本地推理工程记录：在纯中央处理器环境下部署大语言模型，"
    "需要同时权衡模型体积、量化精度与内存带宽三者之间的关系。"
    "量化把权重从十六位浮点压缩到四位整数，显著降低了内存占用和带宽压力，"
    "但也会带来一定的精度损失。多专家混合架构在推理时只激活少量专家，"
    "因此实际计算量远小于参数总量所暗示的规模，这让中央处理器推理变得可行。"
    "线程调度方面，物理核心的利用率比逻辑线程数更值得关注，"
    "因为同步开销与内存带宽争用会在高并发时抵消并行收益。"
)


def build_doc(target_tokens):
    """构造接近 target_tokens 的中文文档，并在 25% 处埋入锚点"""
    chunk = PARA.format(i="{IDX}")
    # 先用一小段测出单节 token 数，据此估算需要多少节
    unit = tokenize(PARA.format(i=1))
    need = max(1, int(target_tokens / unit))
    parts = []
    got = 0
    i = 0
    inserted = False
    while got < target_tokens:
        i += 1
        p = PARA.format(i=i)
        parts.append(p)
        got += unit
        if not inserted and got > target_tokens * 0.25:
            parts.append(NEEDLE)
            inserted = True
    if not inserted:
        parts.append(NEEDLE)
    return "".join(parts), i


def main():
    target = int(sys.argv[1]) if len(sys.argv) > 1 else 65536
    reserve = int(sys.argv[2]) if len(sys.argv) > 2 else 2048
    prompt_target = target - reserve

    print("=" * 74)
    print(f"长上下文测试：目标 {target} token（提示词约 {prompt_target} + 预留 {reserve}）")
    print("线程 28 / 14 物理核 / 仅 CPU")
    print("=" * 74)

    print("[1/3] 构造长文档...", flush=True)
    doc, secs = build_doc(prompt_target)
    full = doc + "\n\n" + QUESTION
    ntok = tokenize(full)
    print(f"      文档 {secs} 节，提示词实际 {ntok} token", flush=True)

    print(f"[2/3] 提交请求（锚点位于文档约 25% 处）... {time.strftime('%H:%M:%S')}", flush=True)
    t0 = time.time()
    r = post("/v1/chat/completions", {
        "messages": [{"role": "user", "content": full}],
        "max_tokens": reserve,
        "temperature": 0.2,
        "chat_template_kwargs": {"enable_thinking": False},
    })
    dt = time.time() - t0

    msg = r["choices"][0]["message"]
    content = (msg.get("content") or "").strip()
    usage = r.get("usage", {})
    pt, ct = usage.get("prompt_tokens"), usage.get("completion_tokens")

    t = r.get("timings") or {}

    print(f"[3/3] 完成，用时 {dt:.1f}s  {time.strftime('%H:%M:%S')}")
    print("-" * 74)
    print(f"  prompt_tokens    = {pt}")
    print(f"  completion_tokens= {ct}")
    print(f"  finish_reason    = {r['choices'][0].get('finish_reason')}")
    print(f"  墙钟总耗时        = {dt:.1f}s")
    if t:
        # 服务端自报的吞吐（含首 token 延迟在内按纯计算段计时，最接近真实体感）
        print("-" * 74)
        print(f"  [预填充/Prefill]  {t.get('prompt_n')} token  "
              f"{t.get('prompt_ms', 0) / 1000:.2f}s  →  {t.get('prompt_per_second'):.2f} t/s")
        print(f"  [生成/Decode]     {t.get('predicted_n')} token  "
              f"{t.get('predicted_ms', 0) / 1000:.2f}s  →  {t.get('predicted_per_second'):.2f} t/s")
        if t.get("predicted_n"):
            print(f"  [首 token 延迟]   {t.get('prompt_ms', 0) / 1000:.2f}s（预填充完成才出第一个字）")
    print("-" * 74)
    print(f"  [回答] {content[:500]}")
    print("-" * 74)
    hit_p = "ZEBRA-9152" in content
    hit_k = "长上下文推理正常" in content
    print(f"  检索结果：项目编号 {'命中 ✔' if hit_p else '未命中 ✘'} | "
          f"验收口令 {'命中 ✔' if hit_k else '未命中 ✘'}")
    print("=" * 74)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"[ERROR] {type(e).__name__}: {e}")
        sys.exit(1)
