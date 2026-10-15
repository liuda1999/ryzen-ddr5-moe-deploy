"""只读解析 GGUF 文件头的元数据（不加载张量），用于确认架构与关键参数。"""
import struct
import sys

GGUF_MAGIC = b"GGUF"

# GGUF metadata value types
TYPE_NAMES = {
    0: "UINT8", 1: "INT8", 2: "UINT16", 3: "INT16", 4: "UINT32", 5: "INT32",
    6: "FLOAT32", 7: "BOOL", 8: "STRING", 9: "ARRAY", 10: "UINT64", 11: "INT64",
    12: "FLOAT64",
}


def read_string(f):
    (n,) = struct.unpack("<Q", f.read(8))
    return f.read(n).decode("utf-8", errors="replace")


def read_value(f, vtype):
    if vtype == 8:  # STRING
        return read_string(f)
    if vtype == 7:  # BOOL
        return struct.unpack("<?", f.read(1))[0]
    if vtype in (0, 1):
        return struct.unpack("<B", f.read(1))[0]
    if vtype in (2, 3):
        return struct.unpack("<H", f.read(2))[0]
    if vtype in (4, 5):
        return struct.unpack("<I", f.read(4))[0]
    if vtype == 6:
        return struct.unpack("<f", f.read(4))[0]
    if vtype in (10, 11):
        return struct.unpack("<Q", f.read(8))[0]
    if vtype == 12:
        return struct.unpack("<d", f.read(8))[0]
    if vtype == 9:  # ARRAY
        (elem_type,) = struct.unpack("<I", f.read(4))
        (count,) = struct.unpack("<Q", f.read(8))
        if count > 64:  # 只预览前若干个，避免长数组
            for _ in range(16):
                read_value(f, elem_type)
            return f"<array[{count}] of {TYPE_NAMES.get(elem_type, elem_type)} ...>"
        return [read_value(f, elem_type) for _ in range(count)]
    raise ValueError(f"unknown type {vtype}")


def main(path):
    with open(path, "rb") as f:
        magic = f.read(4)
        if magic != GGUF_MAGIC:
            print(f"[ERROR] 不是 GGUF 文件: magic={magic!r}")
            return 1
        version, tensor_count, kv_count = struct.unpack("<IQQ", f.read(20))
        print(f"GGUF version      : {version}")
        print(f"tensor count      : {tensor_count}")
        print(f"metadata kv count : {kv_count}")
        print("-" * 60)

        keys_of_interest = (
            "general.architecture",
            "general.name",
            "general.basename",
            "general.finetune",
            "general.file_type",
            "general.quantization_version",
        )
        arch = None
        counters = {}
        for _ in range(kv_count):
            try:
                key = read_string(f)
                (vtype,) = struct.unpack("<I", f.read(4))
                val = read_value(f, vtype)
            except Exception as e:
                print(f"[WARN] 元数据解析中断: {e}")
                break
            if key in keys_of_interest:
                print(f"{key:34s} = {val}")
                if key == "general.architecture":
                    arch = val
            elif key.endswith((".block_count", ".context_length",
                               ".embedding_length", ".expert_count",
                               ".expert_used_count", ".feed_forward_length",
                               ".attention.head_count")):
                counters[key] = val

        print("-" * 60)
        if arch:
            print(f">>> 架构 (general.architecture) = {arch}")
        for k in sorted(counters):
            print(f"{k:34s} = {counters[k]}")
        return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
