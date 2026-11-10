# -*- coding: utf-8 -*-
"""CI 门禁：核对分发包清单与全项目的模型数值、随包文件哈希是否一致。

用法：
    python _维护脚本\\check_manifest.py

为什么单独做这一步，而不是把 verify_package.py 直接塞进 CI：
  verify_package.py 是目标机工具，允许模型缺失；而 CI 的全新 checkout 里
  没有模型、也没有可选的 ggml-cuda.dll。既要在 CI 里保住「清单不被悄悄改坏」，
  又不能因为模型不存在而失败，所以拆成这个仓库侧检查。

检查项：
  1. 清单里三个模型行齐全、都标 *（可选）、字节数等于 model_catalog.py、
     SHA256 列为 (未计算)
  2. 清单无重复条目（历史上【2】/【4】分节条件重叠，把 下载模型.md 写了两遍，
     声明 69 个文件却解析出 70 行）
  3. 启动大模型_StartModel.bat 与 gen_toggle.py 的 DL_BYTES 与 catalog 一致
  4. llama.cpp\\models\\下载模型.md 第四节的精确字节数表与 catalog 一致
  5. 所有非模型、且实际存在的清单条目：大小 + SHA256 与磁盘一致
     （缺失的可选文件跳过）

覆盖不到的：模型文件本身、真实推理。那些仍需上机验证。
"""
import hashlib
import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import model_catalog                         # noqa: E402
from verify_package import parse_manifest, MANIFEST, sha256  # noqa: E402


def norm(path):
    """清单里是反斜杠，统一成正斜杠再比对。"""
    return path.replace('\\', '/').lstrip('*')


def main():
    errors = []

    def err(msg):
        errors.append(msg)

    if not os.path.exists(MANIFEST):
        print('找不到分发包清单：%s' % MANIFEST)
        return 1

    rows = parse_manifest(MANIFEST)
    print('清单条目：%d 行' % len(rows))
    if not rows:
        print('清单里没有解析到可校验的记录。')
        return 1

    # --- 1. 重复条目 -----------------------------------------------------
    seen = {}
    for rel, size, h in rows:
        key = norm(rel)
        if key in seen:
            err('清单里有重复条目：%s（分节条件重叠会让该文件被校验两次）' % key)
        seen[key] = (rel, size, h)
    print('唯一路径：%d 个' % len(seen))

    # --- 2. 模型行：齐全 / 可选 / 官方值 / 不记哈希 -----------------------
    for name, official in model_catalog.MODELS.items():
        key = norm(model_catalog.model_rel(name))
        if key not in seen:
            err('清单缺少模型参考行：%s' % key)
            continue
        rel, size, h = seen[key]
        if not rel.startswith('*'):
            err('模型行没有标 *（可选）：%s —— 会被误判成缺件' % key)
        if size != official:
            err('模型字节数与官方值不符：%s 清单=%d 官方=%d' % (key, size, official))
        if h != '(未计算)':
            err('模型行不应带 SHA256（不随包分发）：%s' % key)
    print('模型参考行：%d 个，均与官方值一致' % len(model_catalog.MODELS))

    # --- 3. 启动脚本 / 生成器的 DL_BYTES ---------------------------------
    expect = set(model_catalog.MODELS[n] for n in model_catalog.PRIMARY_MODELS)
    dl_re = re.compile(r'set "DL_BYTES=(\d+)"')
    for path, enc in (('启动大模型_StartModel.bat', 'gbk'),
                      ('_维护脚本/gen_toggle.py', 'utf-8')):
        full = os.path.join(ROOT, path)
        if not os.path.exists(full):
            err('找不到 %s' % path)
            continue
        text = io.open(full, encoding=enc, errors='replace').read()
        got = set(int(x) for x in dl_re.findall(text))
        if got != expect:
            err('%s 的 DL_BYTES=%s，与 model_catalog 的 %s 不一致'
                % (path, sorted(got), sorted(expect)))
    print('DL_BYTES：启动脚本 / 生成器与 catalog 一致')

    # --- 3b. verify_package.py 的截断阈值与 catalog 一致 ------------------
    vp_path = os.path.join(HERE, 'verify_package.py')
    vp = io.open(vp_path, encoding='utf-8', errors='replace').read()
    m = re.search(r'^MODEL_TRUNCATE_RATIO\s*=\s*([0-9.]+)', vp, re.M)
    if not m:
        err('verify_package.py 里找不到 MODEL_TRUNCATE_RATIO')
    elif float(m.group(1)) != model_catalog.TRUNCATE_RATIO:
        err('verify_package.py 的截断阈值 %s 与 model_catalog.TRUNCATE_RATIO=%s 不一致'
            % (m.group(1), model_catalog.TRUNCATE_RATIO))
    else:
        print('截断阈值：verify_package.py 与 catalog 一致（%s）' % m.group(1))

    # --- 4. 下载模型.md 第四节的精确字节数表 ------------------------------
    doc_path = os.path.join(ROOT, 'llama.cpp', 'models', '下载模型.md')
    if not os.path.exists(doc_path):
        err('找不到 llama.cpp/models/下载模型.md')
    else:
        doc = io.open(doc_path, encoding='utf-8', errors='replace').read()
        for name, official in model_catalog.MODELS.items():
            m = re.search(r'\|\s*' + re.escape(name) + r'\s*\|\s*([\d,]+)\s*\|', doc)
            if not m:
                err('下载模型.md 里找不到 %s 的精确字节数' % name)
                continue
            got = int(m.group(1).replace(',', ''))
            if got != official:
                err('下载模型.md 里 %s 写的是 %d，官方值是 %d' % (name, got, official))
    print('下载模型.md：精确字节数表与 catalog 一致')

    # --- 5. 随包文件：大小 + SHA256 --------------------------------------
    checked = skipped = 0
    for rel, size, h in rows:
        key = norm(rel)
        if key.lower().endswith('.gguf'):
            continue                       # 模型不进仓库，跳过
        full = os.path.join(ROOT, key.replace('/', os.sep))
        if not os.path.exists(full):
            if rel.startswith('*'):
                skipped += 1               # 可选文件（如 ggml-cuda.dll）
                continue
            err('清单里的必需文件在仓库中不存在：%s' % key)
            continue
        real = os.path.getsize(full)
        if real != size:
            err('大小不符：%s 清单=%d 实际=%d' % (key, size, real))
            continue
        if h != '(未计算)' and sha256(full) != h:
            err('SHA256 不符：%s（改了文件请重新运行 make_manifest.py）' % key)
            continue
        checked += 1
    print('随包文件校验：%d 个一致，%d 个可选文件未随仓库分发（跳过）'
          % (checked, skipped))

    if errors:
        print()
        print('发现 %d 个问题：' % len(errors))
        for e in errors:
            print('  -', e)
        print()
        print('清单一致性检查失败。改完请重新运行 make_manifest.py。')
        return 1
    print()
    print('清单一致性检查通过。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
