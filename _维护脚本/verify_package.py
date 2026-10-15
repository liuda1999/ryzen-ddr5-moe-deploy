# -*- coding: utf-8 -*-
"""按 分发包清单.txt 校验当前目录的文件是否完整（精确字节数 + SHA256）。

在目标机上运行即可确认拷贝过程有没有丢文件或损坏：
    python _维护脚本\\verify_package.py

输出标记：
    [OK]       大小与哈希都一致
    [大小不符] 大小不一致（拷贝不完整或文件损坏）
    [哈希不符] 大小一致但内容不同（被改动过）
    [缺失]     文件不存在
    [跳过]     清单里该文件没算哈希（例如模型只记了大小）
"""
import hashlib
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
MANIFEST = os.path.join(ROOT, '分发包清单.txt')


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
        if not line or line.startswith(('=', '-', ' ', '【', '合计', '格式', '校验', '生成', '源目录', '文件数', 'Qwen')):
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
        print('请把 分发包清单.txt 一起拷贝过来，或先在源机器上运行 make_manifest.py。')
        return 1

    rows = parse_manifest(MANIFEST)
    if not rows:
        print('清单里没有解析到可校验的记录，请检查文件内容。')
        return 1

    print('清单文件：%s' % MANIFEST)
    print('待校验条目：%d' % len(rows))
    print('-' * 72)

    ok = skip = bad = missing = 0
    problems = []

    for rel, exp_size, exp_hash in rows:
        optional = rel.startswith('*')
        if optional:
            rel = rel[1:]

        full = os.path.join(ROOT, rel)
        if not os.path.exists(full):
            if optional:
                print('[未带]     %s  （可选文件，不算问题）' % rel)
                skip += 1
                continue
            print('[缺失]     %s' % rel)
            missing += 1
            problems.append(rel)
            continue

        real = os.path.getsize(full)
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
    return 0


if __name__ == '__main__':
    sys.exit(main())
