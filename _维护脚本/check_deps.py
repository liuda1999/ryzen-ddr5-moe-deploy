# -*- coding: utf-8 -*-
"""解析 PE 导入表，列出构建产物的外部 DLL 依赖，判断目标设备前置条件。

不依赖任何第三方库，直接解析 PE 结构。
"""
import os
import struct
import sys
import glob

BIN = r"E:\llm-cpp\llama.cpp\build-zen5\bin"

# Windows 自带、无需额外安装的 DLL 前缀
SYSTEM_PREFIX = (
    'api-ms-win-', 'ext-ms-',
)
SYSTEM_NAMES = {
    'kernel32.dll', 'kernelbase.dll', 'user32.dll', 'advapi32.dll', 'shell32.dll',
    'ole32.dll', 'oleaut32.dll', 'ws2_32.dll', 'wsock32.dll', 'ntdll.dll',
    'version.dll', 'psapi.dll', 'bcrypt.dll', 'crypt32.dll', 'secur32.dll',
    'gdi32.dll', 'comdlg32.dll', 'comctl32.dll', 'shlwapi.dll', 'iphlpapi.dll',
    'dbghelp.dll', 'mfplat.dll', 'mf.dll', 'mfuuid.dll', 'setupapi.dll',
    'userenv.dll', 'wldap32.dll', 'normaliz.dll', 'powrprof.dll', 'dnsapi.dll',
    'dxgi.dll', 'd3d11.dll', 'opengl32.dll', 'glu32.dll', 'winmm.dll',
    'ucrtbase.dll', 'msvcrt.dll', 'rpcrt4.dll', 'cfgmgr32.dll', 'bcryptprimitives.dll',
}
# VC++ 运行时（目标机需要安装 VC++ 2015-2022 Redistributable x64）
VCRUNTIME = (
    'vcruntime140', 'vcruntime140_1', 'msvcp140', 'concrt140', 'vccorlib140',
    'msvcp140_1', 'msvcp140_2', 'msvcp140_atomic_wait', 'msvcp140_codecvt_ids',
)


def read_pe_imports(path):
    """返回该 PE 文件导入的 DLL 名列表（小写）。"""
    with open(path, 'rb') as f:
        data = f.read()
    if data[:2] != b'MZ':
        return None
    e_lfanew = struct.unpack_from('<I', data, 0x3C)[0]
    if data[e_lfanew:e_lfanew + 4] != b'PE\0\0':
        return None
    coff = e_lfanew + 4
    num_sections = struct.unpack_from('<H', data, coff + 2)[0]
    size_opt = struct.unpack_from('<H', data, coff + 16)[0]
    opt = coff + 20
    magic = struct.unpack_from('<H', data, opt)[0]
    dd = opt + (112 if magic == 0x20b else 96)
    imp_rva, _ = struct.unpack_from('<II', data, dd + 8)   # 索引 1 = Import Table

    sec = opt + size_opt
    sections = []
    for i in range(num_sections):
        off = sec + i * 40
        vsize, vaddr, rawsize, rawptr = struct.unpack_from('<IIII', data, off + 8)
        sections.append((vaddr, vsize, rawptr, rawsize))

    def rva2off(rva):
        for vaddr, vsize, rawptr, rawsize in sections:
            if vaddr <= rva < vaddr + max(vsize, rawsize):
                return rawptr + (rva - vaddr)
        return None

    off = rva2off(imp_rva)
    if off is None:
        return []
    names = []
    while True:
        entry = data[off:off + 20]
        if len(entry) < 20 or entry == b'\0' * 20:
            break
        name_rva = struct.unpack_from('<I', entry, 12)[0]
        if name_rva == 0:
            break
        no = rva2off(name_rva)
        if no is None:
            break
        end = data.find(b'\0', no)
        names.append(data[no:end].decode('ascii', 'ignore').lower())
        off += 20
    return names


def main():
    local = {f.lower() for f in os.listdir(BIN)}
    targets = sorted(glob.glob(os.path.join(BIN, '*.exe')) +
                     glob.glob(os.path.join(BIN, '*.dll')))
    external = {}
    for p in targets:
        try:
            deps = read_pe_imports(p) or []
        except Exception as e:
            print('!! 解析失败', os.path.basename(p), e)
            continue
        for d in deps:
            if d in local:          # 项目自带 DLL，随包分发
                continue
            external.setdefault(d, set()).add(os.path.basename(p))

    sys_dlls, vc_dlls, other = [], [], []
    for d in sorted(external):
        if d.startswith(VCRUNTIME) or d.startswith('ucrtbase'):
            vc_dlls.append(d)
        elif d.startswith(SYSTEM_PREFIX) or d in SYSTEM_NAMES:
            sys_dlls.append(d)
        else:
            other.append(d)

    print('=' * 70)
    print('构建产物外部依赖分析（目录：%s）' % BIN)
    print('=' * 70)
    print('\n[Windows 系统 DLL] %d 个 —— 目标机自带，无需处理' % len(sys_dlls))
    for d in sys_dlls:
        print('   ', d)
    print('\n[VC++ 运行时 DLL] %d 个 —— 目标机需要 VC++ 2015-2022 Redistributable (x64)' % len(vc_dlls))
    for d in vc_dlls:
        print('   ', d)
    print('\n[其它 / 需人工确认] %d 个' % len(other))
    for d in other:
        print('   ', d, '  <-- 被', ', '.join(sorted(external[d])[:3]), '引用')
    if not other:
        print('    （无）')

    # 本机是否存在这些运行时
    print('\n' + '-' * 70)
    print('本机运行时自检：')
    probe = ['vcruntime140.dll', 'vcruntime140_1.dll', 'msvcp140.dll']
    for d in probe:
        found = None
        for root in [os.path.join(os.environ.get('SystemRoot', r'C:\Windows'), 'System32')]:
            f = os.path.join(root, d)
            if os.path.exists(f):
                found = f
        print('   %-24s %s' % (d, found or '未找到（本机可能有 App-local 副本）'))

    # 检查 bin 目录里是否自带这些运行时（自包含分发）
    print('\nbin 目录内是否随包附带运行时：')
    for d in probe + ['msvcp140_atomic_wait.dll']:
        print('   %-28s %s' % (d, '是' if d in local else '否'))


if __name__ == '__main__':
    main()
