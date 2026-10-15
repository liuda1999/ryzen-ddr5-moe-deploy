# -*- coding: utf-8 -*-
"""打包「不含模型」的免安装发行包，供 GitHub Releases 附件使用。

用法：
    python make_release.py                 # 版本号取 0.2.6
    python make_release.py 0.2.6           # 指定版本号
    python make_release.py 0.2.6 D:\\out   # 指定输出目录

输出：
    <输出目录>\\ryzen-ddr5-moe-deploy-<版本>-no-model.zip

打进包的内容 = 能直接跑起来的最小集合：
    - 根目录脚本与文档（含 README / LICENSE）
    - _维护脚本\\ 下的活跃工具（不含 _历史补丁 与 __pycache__）
    - llama.cpp\\build-zen5\\bin\\  运行所需的 exe / dll（含 VC++ 运行时）
    - llama.cpp\\models\\下载模型.md  模型下载指引（占位，不含 .gguf）

不打进包的内容：
    - 模型文件（22 GB+）、构建中间产物、源码树、日志、密钥
    - **CUDA 后端 ggml-cuda.dll**（见 BIN_SKIP）

为什么排除 ggml-cuda.dll（2026-10-15 定）：
    它是可选组件，且本项目编出的那一份只含 sm_61（Pascal）机器码 ——
    放到公开附件里，Ampere / Ada 用户下完也用不了，只会白占 30 MB 并
    引来误解。公开包维持「零 CUDA 二进制」，需要的人在 README 里按
    「自编 _维护脚本\\build-cuda-backend.bat」或「取官方预编译包」两条路自取。
    启动脚本的 GPU_MODE=auto 在缺这个文件时会自动退回纯 CPU，不影响使用。
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
    # README 顶部引用的项目 Logo；不带的话包内 README 的图片会显示不出来
    os.path.join("assets", "logo.jpg"),
]

# 维护脚本目录里需要跳过的内容
MAINT_SKIP = {"_历史补丁", "__pycache__", "_旧脚本备份"}

# bin\ 里不打包的文件名（精确匹配，大小写不敏感）
# ggml-cuda.dll：可选组件，且本地那份只含 sm_61（Pascal）机器码，
# 放进公开包对其它代际的卡没用。详见文件头说明。
BIN_SKIP = {"ggml-cuda.dll"}


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
    version = sys.argv[1] if len(sys.argv) > 1 else "0.2.6"
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
            if fn.lower() in {s.lower() for s in BIN_SKIP}:
                print("  [排除] %s（可选组件，不入公开包）" % os.path.join(reldir, fn))
                continue
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
