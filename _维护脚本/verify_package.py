# -*- coding: utf-8 -*-
"""按 分发包清单_PackageManifest.txt 校验当前目录的分发包是否完整。

在目标机上运行即可确认拷贝过程有没有丢文件或损坏：
    python _维护脚本\\verify_package.py

两套判定标准（重要）：
  - 随包文件（脚本 / 文档 / 二进制）：精确字节数 + SHA256 严格比对，
    任何一个不符都判「分发包不完整」。
  - 模型文件（*.gguf）：不随 GitHub 分发包提供，由用户按 README 自行下载。
    缺失不算问题；大小与清单里的【官方参考值】不同也只给提示
    （上游可能换版本 / 换镜像），不当成包损坏；只有不足官方值一半的
    明显截断才拦下。清单里的模型字节数取自 _维护脚本\\model_catalog.py。

  历史教训：早期版本把模型列为「必需」并用本机旧文件的大小做精确比对，
  导致 no-model 包必然报「分发包不完整」，按 README 下载官方模型的机器
  也必然报「大小不符」。模型不是包的一部分，不能进包完整性判定。

输出标记：
    [OK]       大小与哈希都一致
    [大小不符] 大小不一致（拷贝不完整或文件损坏）
    [哈希不符] 大小一致但内容不同（被改动过）
    [缺失]     必需文件不存在
    [未带]     可选文件 / 模型未随包提供，不算问题
    [提示]     模型版本与官方参考值不同，请自行确认
    [跳过]     清单里该文件没算哈希
"""
import hashlib
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
MANIFEST = os.path.join(ROOT, '分发包清单_PackageManifest.txt')

# 与 _维护脚本/model_catalog.py 的 TRUNCATE_RATIO 保持一致（CI 会核对）。
# 用相对阈值而不是固定 1 GiB：mmproj-BF16.gguf 官方只有约 0.84 GiB，
# 固定阈值会把合法文件误判成损坏。
# 这里刻意不 import model_catalog：本脚本要能在只拷了清单 + 本文件的
# 目标机上独立运行。
MODEL_TRUNCATE_RATIO = 0.5


def sha256(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def parse_manifest(path):
    """只认三列 Tab 分隔的数据行，跳过所有说明文字。"""
    rows = []
    for raw in io.open(path, encoding='utf-8'):
        line = raw.rstrip('\n').rstrip('\r')
        if not line or line.startswith(('=', '-', ' ', '【', '合计', '格式', '校验',
                                        '生成', '源目录', '文件数', 'Qwen', '清单',
                                        '模型', '关于')):
            continue
        parts = line.split('\t')
        if len(parts) != 3:
            continue
        rel, size_str, h = parts
        if not size_str.isdigit():
            continue
        rows.append((rel, int(size_str), h))
    return rows


def main():
    if not os.path.exists(MANIFEST):
        print('找不到清单文件：%s' % MANIFEST)
        print('请把 分发包清单_PackageManifest.txt 一起拷贝过来，或先在源机器上运行 make_manifest.py。')
        return 1

    rows = parse_manifest(MANIFEST)
    if not rows:
        print('清单里没有解析到可校验的记录，请检查文件内容。')
        return 1

    print('清单文件：%s' % MANIFEST)
    print('待校验条目：%d' % len(rows))
    print('-' * 72)

    ok = skip = bad = missing = 0
    model_absent = model_hint = 0
    problems = []

    for rel, exp_size, exp_hash in rows:
        optional = rel.startswith('*')
        if optional:
            rel = rel[1:]
        is_model = rel.lower().endswith('.gguf')
        full = os.path.join(ROOT, rel)

        if not os.path.exists(full):
            if optional:
                if is_model:
                    print('[未带]     %s  （模型不随包分发，按 README 自行下载；不算问题）' % rel)
                    model_absent += 1
                else:
                    print('[未带]     %s  （可选文件，不算问题）' % rel)
                skip += 1
                continue
            print('[缺失]     %s' % rel)
            missing += 1
            problems.append(rel)
            continue

        real = os.path.getsize(full)

        if is_model:
            # 模型来自第三方下载，只拦明显截断，不参与包完整性判定。
            if real < exp_size * MODEL_TRUNCATE_RATIO:
                print('[大小不符] %s  实际 %d 字节，不足官方值 %d 的一半，判定为下载不完整'
                      % (rel, real, exp_size))
                bad += 1
                problems.append(rel)
            elif real != exp_size:
                print('[提示]     %s  实际 %d 字节，官方参考值 %d 字节'
                      '（可能是不同量化版本或镜像更新，请自行确认；不算包损坏）'
                      % (rel, real, exp_size))
                model_hint += 1
                skip += 1
            elif exp_hash == '(未计算)':
                print('[OK]       %s  （大小与官方值一致，跳过哈希）' % rel)
                skip += 1
            elif sha256(full) == exp_hash:
                print('[OK]       %s' % rel)
                ok += 1
            else:
                print('[哈希不符] %s  （文件被改动或损坏）' % rel)
                bad += 1
                problems.append(rel)
            continue

        # 随包文件：严格校验，不放宽。
        if real != exp_size:
            print('[大小不符] %s  期望 %d，实际 %d 字节' % (rel, exp_size, real))
            bad += 1
            problems.append(rel)
            continue

        if exp_hash == '(未计算)':
            print('[跳过]     %s  （仅校验大小，通过）' % rel)
            skip += 1
            continue

        if sha256(full) == exp_hash:
            print('[OK]       %s' % rel)
            ok += 1
        else:
            print('[哈希不符] %s  （文件被改动或损坏）' % rel)
            bad += 1
            problems.append(rel)

    print('-' * 72)
    print('一致 %d，跳过 %d，异常 %d，缺失 %d' % (ok, skip, bad, missing))
    print('模型：未随包 %d，版本差异提示 %d（模型不参与分发包完整性判定）'
          % (model_absent, model_hint))
    if problems:
        print()
        print('有问题的文件：')
        for p in problems:
            print('  -', p)
        print()
        print('结论：分发包不完整，建议重新拷贝。')
        return 1
    print()
    print('结论：分发包完整，可以使用。')
    if model_absent:
        print('提示：模型文件需按 README.md「模型下载」自行下载，放入 llama.cpp\\models\\。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
