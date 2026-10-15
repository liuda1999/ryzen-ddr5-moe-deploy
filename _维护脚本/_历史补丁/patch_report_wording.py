# -*- coding: utf-8 -*-
"""调整验收报告措辞：把分发配套问题与脚本行为问题分开表述。"""
import io
import re

P = r"E:\llm-cpp\验收报告.md"
s = io.open(P, encoding='utf-8').read()

s = s.replace(
    '结论是：**确实踩到了 2 个会导致分发后完全用不了的硬伤**，都已修复。',
    '结论是：**确实踩到了 2 个"换台机器就用不了"的分发配套遗漏**，'
    '已通过"随包附带 + 文档写明"解决。')

s = re.sub(r'- \*\*修复\*\*：从 VS 官方 redist 目录',
           '- **处理**：\n  1. 从 VS 官方 redist 目录', s, count=1)

s = s.replace(
    '**目标机无需安装 VC++ Redistributable**。',
    '**目标机无需安装 VC++ Redistributable**；\n'
    '  2. 在 `使用说明.md` 第 3.1 节写明依赖清单、自检方法，以及被安全软件清理后的补救方式。')

s = re.sub(r'- \*\*修复\*\*：改为脚本读出密钥内容后以 `--api-key <值>` 传参。',
           '- **处理**：\n'
           '  1. 脚本层改造：读出密钥内容后以 `--api-key <值>` 传参，绕开路径解析；\n'
           '  2. 在 `使用说明.md` 第 5.1 节说明该限制、规避方式，以及推荐用英文路径的理由。',
           s, count=1)

s = s.replace('### 中等级', '### 二、脚本行为类（已直接修复）', 1)
s = s.replace('### 轻微\n\n', '')

io.open(P, 'w', encoding='utf-8', newline='\r\n').write(s)
print('验收报告措辞已调整')
