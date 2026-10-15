# -*- coding: utf-8 -*-
"""让基准脚本自动读取 api-key.txt 并携带鉴权头。"""
import io

FILES = [r"E:\llm-cpp\_维护脚本\bench_ctx.py", r"E:\llm-cpp\_维护脚本\chat_test.py"]

HELPER = '''
def _load_api_key():
    """从工作区根目录 api-key.txt 读取密钥（跳过注释行），没有就返回空串。"""
    import os
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "api-key.txt")
    try:
        with io.open(p, encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    return line
    except OSError:
        pass
    return ""


API_KEY = _load_api_key()
'''

for p in FILES:
    s = io.open(p, encoding='utf-8').read()
    if '_load_api_key' in s:
        print(p, '已处理过，跳过')
        continue

    # 需要 io 模块
    if 'import io' not in s:
        s = s.replace('import urllib.request', 'import io\nimport urllib.request', 1)

    # 插入辅助函数（放在 HOST 定义之前）
    anchor = 'HOST = "http://127.0.0.1:35035"'
    assert anchor in s, (p, 'HOST anchor')
    s = s.replace(anchor, HELPER.strip() + '\n\n' + anchor, 1)

    # 请求头带鉴权
    old_hdr = 'headers={"Content-Type": "application/json"},'
    new_hdr = ('headers={"Content-Type": "application/json",\n'
               '                 **( {"Authorization": "Bearer " + API_KEY} if API_KEY else {} )},')
    assert old_hdr in s, (p, 'header anchor')
    s = s.replace(old_hdr, new_hdr, 1)

    io.open(p, 'w', encoding='utf-8', newline='\r\n').write(s)
    print(p, '已更新')
