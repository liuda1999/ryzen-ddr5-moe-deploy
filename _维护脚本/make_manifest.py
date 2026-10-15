# -*- coding: utf-8 -*-
"""生成分发包清单（精确字节数 + SHA256），用于分发前后的完整性校验。

产物：项目根目录的 分发包清单.txt

用法：
    python make_manifest.py                # 生成清单（模型只记大小，不记哈希）
    python make_manifest.py --model-hash   # 连模型也算 SHA256（慢，几分钟）
"""
import hashlib
import io
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

ROOT_REQUIRED = [
    "启动大模型.bat",
    "环境检查.bat",
    "开放局域网端口.bat",
    "README.md",
    "使用说明.md",
    "参数阶梯手册.md",
    "部署说明.txt",
]
ROOT_OPTIONAL = [
    "重新编译.bat",
    "验收报告.md",
    os.path.join("llama.cpp", "models", "下载模型.md"),
]
DIR_REQUIRED = [
    os.path.join("llama.cpp", "build-zen5", "bin"),
]
MODEL_DIR = os.path.join("llama.cpp", "models")
MODEL_FILES = [
    "Qwen3.6-35B-A3B-UD-Q4_K_XL.gguf",
    "Qwen3.6-35B-A3B-UD-IQ3_S.gguf",
    "mmproj-BF16.gguf",
]
EXCLUDED = [
    "llama.cpp 下的源码目录（src / ggml / tools / examples / docs 等）—— 运行不需要",
    "llama.cpp\\build（早期 NATIVE 构建，约 387 MB）",
    "llama.cpp\\build-zen5 下除 bin 之外的中间产物",
    "logs\\（运行日志）",
    "api-key.txt（建议不带，目标机首次启动会自动生成新密钥）",
    "_旧脚本备份\\ 、 _维护脚本\\_历史补丁\\",
]


def sha256(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def human(n):
    v = float(n)
    for unit in ['B', 'KB', 'MB', 'GB']:
        if v < 1024:
            return '%.2f %s' % (v, unit)
        v /= 1024.0
    return '%.2f TB' % v


def main():
    with_model_hash = '--model-hash' in sys.argv
    rows = []          # (rel, size, hash_or_note)
    missing = []

    def collect(rel, do_hash=True, optional=False):
        full = os.path.join(ROOT, rel)
        if not os.path.exists(full):
            missing.append(rel)
            return
        size = os.path.getsize(full)
        h = sha256(full) if do_hash else '(未计算)'
        # 可选文件在路径前加 * 标记：分发包不带它们时，校验只提示、不算异常
        rows.append((('*' + rel) if optional else rel, size, h))

    for f in ROOT_REQUIRED:
        collect(f)
    for f in ROOT_OPTIONAL:
        collect(f, optional=True)
    for d in DIR_REQUIRED:
        full = os.path.join(ROOT, d)
        if not os.path.isdir(full):
            missing.append(d)
            continue
        for name in sorted(os.listdir(full)):
            # GPGPU 后端 DLL 按显卡架构编译，不能随包统一分发（见 llama.cpp/.gitignore
            # 的说明），所以标为可选：分发包里没有它时只提示，不算缺件。
            collect(os.path.join(d, name),
                    optional=name.lower().startswith("ggml-cuda"))
    for m in MODEL_FILES:
        collect(os.path.join(MODEL_DIR, m), do_hash=with_model_hash)

    total = sum(r[1] for r in rows)
    out = []
    out.append('=' * 96)
    out.append('Qwen3.6-35B 本地大模型 —— 分发包清单')
    out.append('=' * 96)
    out.append('生成时间：%s' % time.strftime('%Y-%m-%d %H:%M:%S'))
    out.append('源目录  ：%s' % ROOT)
    out.append('文件数  ：%d      总大小：%s（%.2f GB）'
               % (len(rows), human(total), total / 1024 ** 3))
    out.append('')
    out.append('格式说明：每行三列，用 Tab 分隔 —— 相对路径 / 精确字节数 / SHA256。')
    out.append('          路径前带 * 的是"可选文件"：分发包不带它时不算缺件。')
    out.append('          SHA256 列显示 (未计算) 表示只校验大小（模型文件太大）。')
    out.append('          本文件自身不参与校验。')
    out.append('')
    out.append('Git 仓库说明：')
    out.append('  本清单描述的是【完整分发包】，含主模型与视觉投影两部分。')
    out.append('  模型行的字节数为【本机打包时的实际文件】；官方下载文件的精确字节数')
    out.append('  见 llama.cpp\\models\\下载模型.md 第三节（两者可能因量化版本不同而略有差异）。')
    out.append('  GitHub 仓库出于体积原因不含模型与构建中间产物，')
    out.append('  因此在仓库副本里执行校验会提示模型缺失 —— 这是预期结果。')
    out.append('  仓库使用者请按 README.md 中的链接自行下载模型。')
    out.append('  （当前主模型名：Qwen3.6-35B-A3B-UD-Q4_K_XL.gguf（首选）/ Qwen3.6-35B-A3B-UD-IQ3_S.gguf（备用），来源 unsloth/Qwen3.6-35B-A3B-GGUF）')
    out.append('')
    out.append('校验方法：把本文件连同项目一起拷到目标机，然后运行')
    out.append('    python _维护脚本\\verify_package.py')
    out.append('  或用系统自带命令逐个核对：certutil -hashfile "<文件>" SHA256')
    out.append('')

    sections = [
        ('【1】根目录必需文件', ROOT_REQUIRED),
        ('【2】根目录可选文件（按需带上）', ROOT_OPTIONAL),
    ]
    for title, names in sections:
        out.append('-' * 96)
        out.append(title)
        out.append('-' * 96)
        for rel, size, h in rows:
            # rows 里可选文件带 '*' 前缀，比对时要去掉，否则整节会漏掉
            if rel.lstrip('*') in names:
                out.append('%s\t%d\t%s' % (rel, size, h))
        out.append('')

    out.append('-' * 96)
    out.append('【3】运行产物目录（整包必需，含随包附带的 VC++ 运行时）')
    out.append('-' * 96)
    for rel, size, h in rows:
        # 可选条目带 '*' 前缀，比对前先去前缀，否则它们会被整节漏掉
        if rel.lstrip('*').startswith(('llama.cpp\\build-zen5\\bin',
                                       'llama.cpp/build-zen5/bin')):
            out.append('%s\t%d\t%s' % (rel, size, h))
    out.append('')

    out.append('-' * 96)
    out.append('【4】模型文件（必需）')
    out.append('-' * 96)
    for rel, size, h in rows:
        if rel.lstrip('*').startswith(('llama.cpp\\models', 'llama.cpp/models')):
            out.append('%s\t%d\t%s' % (rel, size, h))
    out.append('')

    out.append('-' * 96)
    out.append('【5】不需要打进包的内容')
    out.append('-' * 96)
    for e in EXCLUDED:
        out.append('  - %s' % e)
    if missing:
        out.append('')
        out.append('-' * 96)
        out.append('【!】以下内容在源目录中未找到，请确认')
        out.append('-' * 96)
        for m in missing:
            out.append('  - %s' % m)

    out.append('')
    out.append('=' * 96)
    out.append('合计：%d 个文件，%s' % (len(rows), human(total)))
    out.append('=' * 96)

    dst = os.path.join(ROOT, '分发包清单.txt')
    io.open(dst, 'w', encoding='utf-8', newline='\r\n').write('\n'.join(out) + '\n')
    print('written:', dst)
    print('files = %d   total = %s' % (len(rows), human(total)))
    if missing:
        print('MISSING:', missing)


if __name__ == '__main__':
    main()
