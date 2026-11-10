# -*- coding: utf-8 -*-
"""生成分发包清单（精确字节数 + SHA256），用于分发前后的完整性校验。

产物：项目根目录的 分发包清单_PackageManifest.txt

用法：
    python make_manifest.py                # 生成清单（模型行只记官方参考值）

重要：模型文件不随包分发，清单里那几行只是【官方发布的精确字节数】，
数值取自 _维护脚本/model_catalog.py（唯一事实源），不读本机模型文件。
本机那两份模型是早期版本，与官方发布值不一致，直接写进清单会让
verify_package.py 把任何正常安装的机器判成「分发包不完整」。
"""
import hashlib
import io
import os
import time

import model_catalog

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

ROOT_REQUIRED = [
    "启动大模型_StartModel.bat",
    "环境检查_EnvCheck.bat",
    "开放局域网端口_OpenLanPort.bat",
    "README.md",
    "使用说明_UserGuide.md",
    "参数阶梯手册_TierManual.md",
    "部署说明_DeployNotes.txt",
    "LICENSE",
    os.path.join("assets", "logo.jpg"),      # README 顶部引用的项目 Logo
]
ROOT_OPTIONAL = [
    "重新编译_Rebuild.bat",
    "验收报告_AcceptanceReport.md",
    os.path.join("llama.cpp", "models", "下载模型.md"),
]
DIR_REQUIRED = [
    os.path.join("llama.cpp", "build-zen5", "bin"),
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
    for unit in ['B', 'KiB', 'MiB', 'GiB']:
        if v < 1024:
            return '%.2f %s' % (v, unit)
        v /= 1024.0
    return '%.2f TiB' % v


def main():
    rows = []          # (rel, size, hash_or_note)，rel 可带 '*' 前缀
    bin_rows = []      # 【3】节专用：不要再用目录前缀去 rows 里捞，会与【2】重叠
    missing = []

    def collect(rel, do_hash=True, optional=False):
        full = os.path.join(ROOT, rel)
        if not os.path.exists(full):
            missing.append(rel)
            return None
        size = os.path.getsize(full)
        h = sha256(full) if do_hash else '(未计算)'
        entry = (('*' + rel) if optional else rel, size, h)
        rows.append(entry)
        return entry

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
            e = collect(os.path.join(d, name),
                        optional=name.lower().startswith("ggml-cuda"))
            if e:
                bin_rows.append(e)

    # 模型行：官方参考值，全部可选，不读本机文件。
    # 主模型二选一、mmproj 按需下载，所以三行都不能是「必需」。
    model_rows = []
    for name, size in model_catalog.MODELS.items():
        model_rows.append(('*' + model_catalog.model_rel(name), size, '(未计算)'))
    rows.extend(model_rows)

    packed = [r for r in rows if not r[0].lstrip('*').lower().endswith('.gguf')]
    packed_total = sum(r[1] for r in packed)

    out = []
    out.append('=' * 96)
    out.append('Qwen3.6-35B 本地大模型 —— 分发包清单')
    out.append('=' * 96)
    out.append('生成时间：%s' % time.strftime('%Y-%m-%d %H:%M:%S'))
    out.append('源目录  ：%s' % ROOT)
    out.append('清单条目：%d 行，随包文件合计 %s（不含模型）' % (len(rows), human(packed_total)))
    out.append('模型参考：%d 行，均为官方精确字节数，不随包分发' % len(model_rows))
    out.append('')
    out.append('格式说明：每行三列，用 Tab 分隔 —— 相对路径 / 精确字节数 / SHA256。')
    out.append('          路径前带 * 的是“可选文件”：分发包不带它时不算缺件。')
    out.append('          SHA256 列显示 (未计算) 表示只校验大小。')
    out.append('          本文件自身不参与校验。')
    out.append('')
    out.append('关于模型（重要）：')
    out.append('  模型不随 GitHub 分发包提供，请按 README.md「模型下载」自行下载，')
    out.append('  放入 llama.cpp\\models\\。主模型 Q4_K_M / IQ3_S 二选一，')
    out.append('  mmproj 只在需要看图时下载，因此【4】三行全部标 *。')
    out.append('  三行的字节数是【官方发布值】，取自 _维护脚本\\model_catalog.py，')
    out.append('  对照表见 llama.cpp\\models\\下载模型.md 第四节；仅供参考，')
    out.append('  不是本机文件的实际大小（本机两份是早期版本，与官方值不同）。')
    out.append('  verify_package.py 不会因模型缺失、或模型版本与官方值不同，')
    out.append('  就判定分发包损坏；它只拦「不足官方值一半的明显截断」。')
    out.append('')
    out.append('校验方法：把本文件连同项目一起拷到目标机，然后运行')
    out.append('    python _维护脚本\\verify_package.py')
    out.append('  或用系统自带命令逐个核对：certutil -hashfile "<文件>" SHA256')
    out.append('')

    def emit(title, entries):
        out.append('-' * 96)
        out.append(title)
        out.append('-' * 96)
        for rel, size, h in entries:
            out.append('%s\t%d\t%s' % (rel, size, h))
        out.append('')

    req_set, opt_set = set(ROOT_REQUIRED), set(ROOT_OPTIONAL)
    emit('【1】根目录必需文件（含授权文件与随包资产）',
         [r for r in rows if r[0].lstrip('*') in req_set])
    emit('【2】根目录可选文件（按需带上）',
         [r for r in rows if r[0].lstrip('*') in opt_set])
    emit('【3】运行产物目录（整包必需，含随包附带的 VC++ 运行时）', bin_rows)
    emit('【4】模型文件（不随包分发 · 官方参考值 · 全部可选）', model_rows)

    out.append('-' * 96)
    out.append('【5】不需要打进包的内容')
    out.append('-' * 96)
    for e in EXCLUDED:
        out.append('  - %s' % e)
    if missing:
        out.append('')
        out.append('-' * 96)
        out.append('【!】以下随包文件在源目录中未找到，请确认')
        out.append('-' * 96)
        for m in missing:
            out.append('  - %s' % m)

    out.append('')
    out.append('=' * 96)
    out.append('合计：%d 行（随包 %d + 模型参考 %d），随包体积 %s'
               % (len(rows), len(packed), len(model_rows), human(packed_total)))
    out.append('=' * 96)

    dst = os.path.join(ROOT, '分发包清单_PackageManifest.txt')
    io.open(dst, 'w', encoding='utf-8', newline='\r\n').write('\n'.join(out) + '\n')
    print('written:', dst)
    print('rows = %d (packed %d + model refs %d), packed = %s'
          % (len(rows), len(packed), len(model_rows), human(packed_total)))
    if missing:
        print('MISSING:', missing)


if __name__ == '__main__':
    main()
