# -*- coding: utf-8 -*-
"""量出 GGUF 模型里各类权重的真实体积分布（用于给"显存要多大"定量）。

用法：
    python gguf_tensor_stats.py [模型路径]
    （不传路径则用项目里默认的 Qwen3.6-35B-A3B-UD-Q4_K_XL.gguf）

为什么需要它：MoE 模型里专家权重占了大头但每 token 只激活一小部分，
把"每 token 必读"的那部分放显存才划算。这个脚本把各类权重的体积量出来，
就能算清"上显存需要多少 VRAM"。具体结论见 参数阶梯手册.md 的 GPU 混合卸载章节。

实现说明：不依赖 ggml 的类型表 —— GGUF 的 tensor info 带有数据区内的 offset，
按 offset 排序后相邻差值即每个张量的实际占用（已含 32 字节对齐），
因此与量化类型无关，不会因版本差异算错。

不依赖任何第三方库，也不需要 ggml 的类型表：
GGUF 的 tensor info 里带有数据区内的 offset，按 offset 排序后
相邻差值就是每个张量的实际占用（已含 32 字节对齐），
因此与量化类型无关，不会因为版本差异算错。
"""
import os
import struct
import sys

PATH = sys.argv[1] if len(sys.argv) > 1 else \
    r"E:\llm-cpp\llama.cpp\models\Qwen3.6-35B-A3B-UD-Q4_K_XL.gguf"

SIMPLE = {0: 1, 1: 1, 2: 2, 3: 2, 4: 4, 5: 4, 6: 4, 7: 1,
          10: 8, 11: 8, 12: 8}


def read_str(f):
    n = struct.unpack('<Q', f.read(8))[0]
    return f.read(n).decode('utf-8', 'replace')


def skip_value(f, t):
    if t == 8:
        n = struct.unpack('<Q', f.read(8))[0]
        f.seek(n, 1)
    elif t == 9:
        at = struct.unpack('<I', f.read(4))[0]
        n = struct.unpack('<Q', f.read(8))[0]
        if at == 8:
            for _ in range(n):
                l = struct.unpack('<Q', f.read(8))[0]
                f.seek(l, 1)
        elif at == 9:
            raise ValueError("嵌套数组，无法跳过")
        else:
            f.seek(SIMPLE[at] * n, 1)
    else:
        f.seek(SIMPLE[t], 1)


def align32(x):
    return (x + 31) // 32 * 32


with open(PATH, 'rb') as f:
    magic = f.read(4)
    assert magic == b'GGUF', "不是 GGUF 文件"
    ver = struct.unpack('<I', f.read(4))[0]
    n_tensors = struct.unpack('<Q', f.read(8))[0]
    n_kv = struct.unpack('<Q', f.read(8))[0]
    print("GGUF 版本 %d，张量 %d 个，元数据 %d 项" % (ver, n_tensors, n_kv))

    arch = None
    n_layer = None
    for _ in range(n_kv):
        key = read_str(f)
        t = struct.unpack('<I', f.read(4))[0]
        if key == 'general.architecture' and t == 8:
            arch = read_str(f)
        elif key.endswith('.block_count') and t == 4:
            n_layer = struct.unpack('<I', f.read(4))[0]
        else:
            skip_value(f, t)
    print("架构 %s，层数 %s" % (arch, n_layer))

    tensors = []
    for _ in range(n_tensors):
        name = read_str(f)
        nd = struct.unpack('<I', f.read(4))[0]
        dims = [struct.unpack('<Q', f.read(8))[0] for _ in range(nd)]
        ttype = struct.unpack('<I', f.read(4))[0]
        off = struct.unpack('<Q', f.read(8))[0]
        tensors.append((off, name, dims, ttype))

    data_start = align32(f.tell())

file_size = os.path.getsize(PATH)
data_size = file_size - data_start
tensors.sort()

sizes = {}
for i, (off, name, dims, ttype) in enumerate(tensors):
    nxt = tensors[i + 1][0] if i + 1 < len(tensors) else data_size
    sizes[name] = (nxt - off, dims, ttype)

MB = 1024.0 * 1024.0


def cat(name):
    if 'token_embd' in name:
        return '词嵌入 token_embd'
    if name.startswith('output'):
        return '输出层 output'
    if 'attn' in name:
        return '注意力 attn_*'
    if '_exps' in name:
        return 'MoE 专家 ffn_*_exps'
    if 'ffn_' in name:
        return '稠密 FFN ffn_*'
    if name.endswith('_norm.weight') or 'norm' in name:
        return '归一化 norm'
    return '其它 ' + name.split('.')[-1]


agg = {}
per_layer_exps = {}
for name, (sz, dims, t) in sizes.items():
    c = cat(name)
    a = agg.setdefault(c, [0, 0])
    a[0] += sz
    a[1] += 1
    if '_exps' in name:
        blk = name.split('.')[1] if name.startswith('blk.') else '?'
        per_layer_exps[blk] = per_layer_exps.get(blk, 0) + sz

total = sum(v[0] for v in sizes.values())
print()
print("数据区总占用：%.2f GiB  (文件 %.2f GiB)" % (data_size / 2**30, file_size / 2**30))
print()
print("%-26s %10s %10s %8s" % ('类别', 'GiB', '占比', '张量数'))
print('-' * 60)
for c, (sz, n) in sorted(agg.items(), key=lambda kv: -kv[1][0]):
    print("%-26s %10.2f %9.1f%% %8d" % (c, sz / 2**30, sz * 100.0 / total, n))
print('-' * 60)
print("%-26s %10.2f %9.1f%% %8d" % ('合计', total / 2**30, 100.0, len(sizes)))

exps = agg.get('MoE 专家 ffn_*_exps', [0, 0])[0]
print()
print("=== 结论用数字 ===")
print("  专家权重合计      : %.2f GiB  (%.1f%%)" % (exps / 2**30, exps * 100.0 / total))
print("  非专家（含注意力/稠密/嵌入/输出/归一化）: %.2f GiB  (%.1f%%)"
      % ((total - exps) / 2**30, (total - exps) * 100.0 / total))
if per_layer_exps:
    vals = sorted(per_layer_exps.values())
    print("  单层专家权重      : %.3f GiB  (共 %d 层)"
          % (vals[0] / 2**30, len(vals)))
