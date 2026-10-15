# -*- coding: utf-8 -*-
"""把生成器脚本里的绝对输出路径改成基于脚本自身位置的相对路径，便于整体分发。"""
import io
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

TARGETS = {
    "gen_toggle.py":   ("启动大模型.bat",   'OUT = r"E:\\llm-cpp\\启动大模型.bat"'),
    "gen_check.py":    ("环境检查.bat",     'OUT = r"E:\\llm-cpp\\环境检查.bat"'),
    "gen_firewall.py": ("开放局域网端口.bat", 'OUT = r"E:\\llm-cpp\\开放局域网端口.bat"'),
}

HEADER = '''import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
'''

for name, (out_file, old_line) in TARGETS.items():
    p = os.path.join(HERE, name)
    if not os.path.exists(p):
        print('  跳过（不存在）', name)
        continue
    s = io.open(p, encoding='utf-8').read()
    if 'HERE = os.path.dirname' in s:
        print('  已处理过', name)
        continue
    assert old_line in s, (name, '未找到 OUT 定义')
    s = s.replace(old_line, 'OUT = os.path.join(ROOT, "%s")' % out_file, 1)
    # 保证 import os 存在（原来就有 import os / import io 等）
    if 'import os' not in s:
        s = s.replace('import io', 'import io\nimport os', 1)
    io.open(p, 'w', encoding='utf-8', newline='\r\n').write(s)
    print('  已改为相对路径', name)

print('完成')
