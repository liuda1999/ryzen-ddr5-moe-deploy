# -*- coding: utf-8 -*-
"""恢复被 patch_check_blocks.py 误删的 [10/10] 局域网检查项。

上一轮重构 [9/10] 时，替换区间的终点定位在"汇总分隔线之前"，
而 [10/10] 恰好落在该区间内，被一起删掉了。
"""
import io
import os

HERE = os.path.dirname(os.path.abspath(__file__))
P = os.path.join(HERE, "gen_check.py")
s = io.open(P, encoding='utf-8').read()

if '[10/10]' in s:
    print('已存在 [10/10]，无需修复')
    raise SystemExit(0)

anchor = 'echo.\necho ============================================================\nif "%FAIL%"=="1" ('
assert anchor in s, '汇总锚点未找到'

LAN_ITEM = '''echo.

echo [10/10] 局域网访问
call :GET_LAN_IP
if defined LAN_IP goto :P10_HASIP
echo         [警告]  未检测到局域网 IPv4，其它设备可能无法访问
set "WARN=1"
goto :P10_KEY
:P10_HASIP
echo         本机 IP  %LAN_IP%
echo         入口     http://%LAN_IP%:%PORT%   ^(需携带密钥^)
:P10_KEY
if not exist "%KEY_FILE%" goto :P10_NOKEY
call :LOAD_KEY
if not defined API_KEY goto :P10_EMPTYKEY
echo         正常    访问密钥已就绪 %KEY_FILE%
goto :P10_FW
:P10_EMPTYKEY
echo         [警告]  密钥文件里没有有效密钥，局域网请求会被拒绝
set "WARN=1"
goto :P10_FW
:P10_NOKEY
echo         [警告]  密钥文件尚未生成（首次启动服务时会自动创建）
set "WARN=1"
:P10_FW
netsh advfirewall firewall show rule name="llama.cpp-%PORT%" >nul 2>&1
if not errorlevel 1 goto :P10_FWOK
echo         [警告]  未发现防火墙放行规则，局域网设备可能连不上
echo                 需用管理员身份执行一次：
echo                 netsh advfirewall firewall add rule name="llama.cpp-%PORT%" dir=in action=allow protocol=TCP localport=%PORT%
goto :P10_END
:P10_FWOK
echo         正常    防火墙已放行 TCP %PORT%
:P10_END
echo.
echo ============================================================
if "%FAIL%"=="1" ('''

s = s.replace(anchor, LAN_ITEM, 1)
io.open(P, 'w', encoding='utf-8', newline='\r\n').write(s)
print('已恢复 [10/10] 局域网检查项')
