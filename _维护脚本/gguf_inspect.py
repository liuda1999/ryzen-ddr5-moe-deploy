#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""读取 GGUF 的元数据与张量名表，用于确认模型是否含 MTP 头 / 多模态投影。"""
import sys, struct

VT = {
    0: "UINT8", 1: "INT8", 2: "UINT16", 3: "INT16", 4: "UINT32", 5: "INT32",
    6: "FLOAT32", 7: "BOOL", 8: "STRING", 9: "ARRAY", 10: "UINT64",
    11: "INT64", 12: "FLOAT64",
}

def read_str(f):
    n = struct.unpack("<Q", f.read(8))[0]
    return f.read(n).decode("utf-8", "replace")

def read_value(f, t):
    if t == 0: return struct.unpack("<B", f.read(1))[0]
    if t == 1: return struct.unpack("<b", f.read(1))[0]
    if t == 2: return struct.unpack("<H", f.read(2))[0]
    if t == 3: return struct.unpack("<h", f.read(2))[0]
    if t == 4: return struct.unpack("<I", f.read(4))[0]
    if t == 5: return struct.unpack("<i", f.read(4))[0]
    if t == 6: return struct.unpack("<f", f.read(4))[0]
    if t == 7: return struct.unpack("<B", f.read(1))[0]
    if t == 8: return read_str(f)
    if t == 10: return struct.unpack("<Q", f.read(8))[0]
    if t == 11: return struct.unpack("<q", f.read(8))[0]
    if t == 12: return struct.unpack("<d", f.read(8))[0]
    if t == 9:  # ARRAY
        at = struct.unpack("<I", f.read(4))[0]
        cnt = struct.unpack("<Q", f.read(8))[0]
        vals = [read_value(f, at) for _ in range(cnt)]
        return (VT.get(at, at), vals)
    raise ValueError("unknown value type %d" % t)

def inspect(path):
    with open(path, "rb") as f:
        if f.read(4) != b"GGUF":
            print("不是 GGUF 文件:", path); return
        ver = struct.unpack("<I", f.read(4))[0]
        n_tensors = struct.unpack("<Q", f.read(8))[0]
        n_kv = struct.unpack("<Q", f.read(8))[0]
        kv = {}
        for _ in range(n_kv):
            k = read_str(f)
            t = struct.unpack("<I", f.read(4))[0]
            v = read_value(f, t)
            kv[k] = v
        # 张量名表
        names = []
        for _ in range(n_tensors):
            nm = read_str(f)
            nd = struct.unpack("<I", f.read(4))[0]
            for _ in range(nd):
                struct.unpack("<Q", f.read(8))[0]
            struct.unpack("<I", f.read(4))[0]  # type
            struct.unpack("<Q", f.read(8))[0]  # offset
            names.append(nm)
    print("==== %s ====" % path)
    print("GGUF 版本:", ver, " 张量数:", n_tensors)
    for key in ["general.architecture", "general.name", "general.parameter_count",
                "general.file_type", "general.size_label"]:
        if key in kv:
            print("  %-28s = %s" % (key, kv[key]))
    arch = kv.get("general.architecture", "")
    for suf in ["block_count", "context_length", "expert_count",
                "expert_used_count", "embedding_length", "feed_forward_length",
                "attention.head_count", "attention.layer_count"]:
        k = "%s.%s" % (arch, suf)
        if k in kv:
            print("  %-28s = %s" % (k, kv[k]))
    # MTP 探测
    nextn = [n for n in names if "nextn" in n.lower()]
    print("  --> MTP 头张量数:", len(nextn), ("（无）" if not nextn else "样例: " + nextn[0]))
    # 多模态探测
    mm = [n for n in names if any(x in n.lower() for x in ["mmproj", "vision", "img", "pixel"])]
    print("  --> 多模态相关张量数:", len(mm), ("（无）" if not mm else "样例: " + mm[0]))
    print()

for p in sys.argv[1:]:
    try:
        inspect(p)
    except Exception as e:
        print("读取失败", p, e)
