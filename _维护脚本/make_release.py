# -*- coding: utf-8 -*-
"""打包「不含模型」的免安装发行包，供 GitHub Releases 附件使用。

用法：
    python make_release.py                 # 版本号取 0.1.0
    python make_release.py 0.2.0           # 指定版本号
    python make_release.py 0.1.0 D:\\out   # 指定输出目录

输出：
    <输出目录>\\ryzen-ddr5-moe-deploy-<版本>-no-model.zip

打进包的内容 = 能直接跑起来的最小集合：
    - 根目录脚本与文档（含 README / LICENSE）
    - _维护脚本\\ 下的活跃工具（不含 _历史补丁 与 __pycache__）
    - llama.cpp\\build-zen5\\bin\\  运行所需的 exe / dll（含 VC++ 运行时）
    - llama.cpp\\models\\下载模型.md  模型下载指引（占位，不含 .gguf）

不打进包的内容：
    - 模型文件（22 GB+）、构建中间产物、源码树、日志、密钥
"""
import io
import os
import sys
import time
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# 根目录：脚本 + 文档 + 实测数据
ROOT_FILES = [
    "启动大模型.bat",
    "环境检查.bat",
    "开放局域网端口.bat",
    "重新编译.bat",
    "README.md",
    "LICENSE",
    "使用说明.md",
    "参数阶梯手册.md",
    "部署说明.txt",
    "验收报告.md",
    "分发包清单.txt",
    "matrix_results.csv",
    "matrix_extra.csv",
]

# 子目录：整目录收录
SUB_DIRS = [
    os.path.join("llama.cpp", "build-zen5", "bin"),
]

# 单独收录的文件
EXTRA_FILES = [
    os.path.join("llama.cpp", "models", "下载模型.md"),
]

# 维护脚本目录里需要跳过的内容
MAINT_SKIP = {"_历史补丁", "__pycache__", "_旧脚本备份"}


def collect_maint():
    """收集 _维护脚本 下的活跃文件（递归，跳过历史补丁与缓存）。"""
    out = []
    base = os.path.join(ROOT, "_维护脚本")
    if not os.path.isdir(base):
        return out
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if d not in MAINT_SKIP]
        for fn in filenames:
            if fn.endswith((".pyc", ".obj", ".exe")):
                continue
            full = os.path.join(dirpath, fn)
            out.append(os.path.relpath(full, ROOT))
    return sorted(out)


def main():
    version = sys.argv[1] if len(sys.argv) > 1 else "0.1.0"
    outdir = sys.argv[2] if len(sys.argv) > 2 else "E:\\llm-cpp-release"

    name = "ryzen-ddr5-moe-deploy-%s-no-model.zip" % version
    os.makedirs(outdir, exist_ok=True)
    dst = os.path.join(outdir, name)

    members = []       # (磁盘绝对路径, zip 内路径)

    for rel in ROOT_FILES:
        full = os.path.join(ROOT, rel)
        if os.path.isfile(full):
            members.append((full, rel))
        else:
            print("  [警告] 缺少文件，已跳过：%s" % rel)

    for rel in collect_maint():
        members.append((os.path.join(ROOT, rel), rel))

    for reldir in SUB_DIRS:
        full = os.path.join(ROOT, reldir)
        if not os.path.isdir(full):
            print("  [警告] 缺少目录，已跳过：%s" % reldir)
            continue
        for fn in sorted(os.listdir(full)):
            p = os.path.join(full, fn)
            if os.path.isfile(p):
                members.append((p, os.path.join(reldir, fn)))

    for rel in EXTRA_FILES:
        full = os.path.join(ROOT, rel)
        if os.path.isfile(full):
            members.append((full, rel))

    # 全部用 ZIP_DEFLATED；.dll/.exe 本身压不动多少，但文档能压掉一大半
    total_raw = 0
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for full, arc in members:
            total_raw += os.path.getsize(full)
            # 固定时间戳，保证同样的输入产出同样的包（便于比对）
            zi = zipfile.ZipInfo(arc, date_time=(2026, 1, 1, 0, 0, 0))
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = 0o644 << 16
            with open(full, "rb") as f:
                z.writestr(zi, f.read())

    zsize = os.path.getsize(dst)
    print("已生成: %s" % dst)
    print("  文件数 : %d" % len(members))
    print("  原始   : %.1f MB" % (total_raw / 1024 / 1024))
    print("  压缩后 : %.1f MB" % (zsize / 1024 / 1024))
    print("  生成于 : %s" % time.strftime("%Y-%m-%d %H:%M:%S"))


if __name__ == "__main__":
    main()
