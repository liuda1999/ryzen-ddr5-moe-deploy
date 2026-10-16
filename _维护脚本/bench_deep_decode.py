# -*- coding: utf-8 -*-
"""
深上下文解码基准（长提示词 + 长回答）。

为什么单独做一个：chat_test.py 的提问只要求一两句答案，服务端
predicted_n 常常只有 20 来个 token，解码速度的样本太薄、容易被
「首 token 抖动」带偏。本脚本把提示词填到接近目标长度，然后**要求
模型写一段长回答**（默认 800 token），用足够的 token 数测解码速度。

用法：
    python bench_deep_decode.py <目标上下文token数> [回答token数]

依赖 chat_test.py（复用它的长文档构造与直连 127.0.0.1 的会话）。
"""
import importlib.util
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))

# 复用 chat_test.py 里的直连会话 / 长文档构造（它只在 __main__ 下跑 main）
_spec = importlib.util.spec_from_file_location("_chat_test", os.path.join(HERE, "chat_test.py"))
ct = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ct)

LONG_Q = (
    "\n\n请认真读完上面这份工程文档，然后写一份不少于 600 字的总结。"
    "要求分点，依次讲清楚：量化带来的收益与代价、MoE 为什么适合 CPU 推理、"
    "线程数该怎么选、内存带宽为什么是瓶颈、显存混合卸载解决的是什么问题。"
    "不要复述原文，用你自己的话概括。"
)


def main():
    target = int(sys.argv[1]) if len(sys.argv) > 1 else 62000
    out_tokens = int(sys.argv[2]) if len(sys.argv) > 2 else 800
    prompt_target = target - out_tokens - 512

    print("=" * 74)
    print(f"深上下文解码基准：提示词约 {prompt_target} token，回答预留 {out_tokens} token")
    print("=" * 74)

    print("[1/2] 构造长文档...", flush=True)
    doc, secs = ct.build_doc(prompt_target)
    full = doc + LONG_Q
    ntok = len(ct.post("/tokenize", {"content": full})["tokens"])
    print(f"      文档 {secs} 节，提示词实际 {ntok} token", flush=True)

    print(f"[2/2] 提交请求... {time.strftime('%H:%M:%S')}", flush=True)
    t0 = time.time()
    r = ct.post("/v1/chat/completions", {
        "messages": [{"role": "user", "content": full}],
        "max_tokens": out_tokens,
        "temperature": 0.2,
        "chat_template_kwargs": {"enable_thinking": False},
    })
    wall = time.time() - t0
    t = r.get("timings") or {}
    content = (r["choices"][0].get("message") or {}).get("content") or ""

    print(f"      完成于 {time.strftime('%H:%M:%S')}，墙钟 {wall:.1f}s")
    print("-" * 74)
    print(f"  prompt_tokens     = {r.get('usage', {}).get('prompt_tokens')}")
    print(f"  completion_tokens = {r.get('usage', {}).get('completion_tokens')}")
    print(f"  finish_reason     = {r['choices'][0].get('finish_reason')}")
    if t:
        print("-" * 74)
        print(f"  [预填充/Prefill]  {t.get('prompt_n')} token  {t.get('prompt_ms', 0)/1000:.2f}s"
              f"  →  {t.get('prompt_per_second'):.2f} t/s")
        print(f"  [生成/Decode]     {t.get('predicted_n')} token  {t.get('predicted_ms', 0)/1000:.2f}s"
              f"  →  {t.get('predicted_per_second'):.2f} t/s")
    print("-" * 74)
    print(f"  [回答开头] {content[:160].replace(chr(10), ' ')}")
    print("=" * 74)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"[ERROR] {type(e).__name__}: {e}")
        sys.exit(1)
