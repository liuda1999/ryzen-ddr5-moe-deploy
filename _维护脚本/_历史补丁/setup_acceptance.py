# -*- coding: utf-8 -*-
"""搭建"模拟分发"验收副本：不同盘符路径 + 与源码/构建中间产物完全隔离。

只放分发必需的东西，用来验证：
  1. 脚本不依赖原目录的绝对路径
  2. 只带 bin 目录时程序能否独立运行
  3. 模型用硬链接共享（不占额外磁盘，避免真拷 21GB）
"""
import os
import shutil
import sys

SRC = r"E:\llm-cpp"
DST = r"E:\llm-cpp-验收测试"

# 分发必需的根目录文件
ROOT_FILES = [
    "启动大模型.bat",
    "环境检查.bat",
    "开放局域网端口.bat",
    "重新编译.bat",
    "参数阶梯手册.md",
    "部署说明.txt",
]
# 模型文件（用硬链接）
MODEL_FILES = [
    "Qwen3.6-35B-A3B-UD-Q4_K_XL.gguf",
    "mmproj-BF16.gguf",
]


def main():
    # 每次都重建，确保干净
    if os.path.exists(DST):
        print("清理旧的验收目录 ...")
        shutil.rmtree(DST, ignore_errors=True)
    os.makedirs(DST)

    bin_dst = os.path.join(DST, "llama.cpp", "build-zen5", "bin")
    models_dst = os.path.join(DST, "llama.cpp", "models")
    os.makedirs(models_dst, exist_ok=True)

    # 1) 根目录脚本与文档
    for f in ROOT_FILES:
        src = os.path.join(SRC, f)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(DST, f))
            print("  复制  %s" % f)

    # 2) 运行产物（整个 bin 目录，含 exe / dll / 运行时）
    src_bin = os.path.join(SRC, "llama.cpp", "build-zen5", "bin")
    print("  复制  bin/ ...")
    shutil.copytree(src_bin, bin_dst)

    # 3) 模型：硬链接（同卷，瞬时完成，不占额外空间）
    for m in MODEL_FILES:
        src = os.path.join(SRC, "llama.cpp", "models", m)
        dst = os.path.join(models_dst, m)
        if os.path.exists(src):
            os.link(src, dst)
            print("  硬链接 %s" % m)

    # 4) 刻意不带 api-key.txt，验证首次启动能否自动生成

    def total(path):
        n = 0
        for root, _, files in os.walk(path):
            for f in files:
                try:
                    n += os.path.getsize(os.path.join(root, f))
                except OSError:
                    pass
        return n

    print("\n验收副本：%s" % DST)
    print("  体积（不含硬链接模型）：%.1f MB" % (total(DST) / 1024 / 1024))
    print("  已刻意不带 api-key.txt / logs / 源码，用于验证自举能力")


if __name__ == '__main__':
    main()
