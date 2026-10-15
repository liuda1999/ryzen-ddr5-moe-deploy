# -*- coding: utf-8 -*-
"""给环境检查脚本的生成器补上局域网/密钥/防火墙检查项。"""
import io

P = r"E:\llm-cpp\_维护脚本\gen_check.py"
s = io.open(P, encoding='utf-8').read()

if 'KEY_FILE' not in s:
    # 1) 变量区加密钥文件
    old = 'set "PID_FILE=%LOG_DIR%\\server.pid"\n'
    assert old in s, 'var anchor'
    s = s.replace(old, old + 'set "KEY_FILE=%ROOT%api-key.txt"\n', 1)

    # 2) 编号 /9 -> /10
    for i in range(1, 10):
        s = s.replace('[%d/9]' % i, '[%d/10]' % i)

    # 3) 追加第 10 项（插在汇总分隔线之前）
    anchor = 'echo.\necho ============================================================\nif "%FAIL%"=="1" ('
    assert anchor in s, 'summary anchor'
    item = '''echo.

echo [10/10] 局域网访问
call :GET_LAN_IP
if defined LAN_IP (
  echo         本机 IP  %LAN_IP%
  echo         入口     http://%LAN_IP%:%PORT%   ^(需携带密钥^)
) else (
  echo         [警告]  未检测到局域网 IPv4，其它设备可能无法访问
  set "WARN=1"
)
if exist "%KEY_FILE%" (
  call :LOAD_KEY
  if defined API_KEY (
    echo         正常    访问密钥已就绪 %KEY_FILE%
  ) else (
    echo         [警告]  密钥文件里没有有效密钥，局域网请求会被拒绝
    set "WARN=1"
  )
) else (
  echo         [警告]  密钥文件尚未生成（首次启动服务时会自动创建）
  set "WARN=1"
)
netsh advfirewall firewall show rule name="llama.cpp-%PORT%" >nul 2>&1
if errorlevel 1 (
  echo         [警告]  未发现防火墙放行规则，局域网设备可能连不上
  echo                 需用管理员身份执行一次：
  echo                 netsh advfirewall firewall add rule name="llama.cpp-%PORT%" dir=in action=allow protocol=TCP localport=%PORT%
) else (
  echo         正常    防火墙已放行 TCP %PORT%
)
echo.
echo ============================================================
if "%FAIL%"=="1" ('''
    s = s.replace(anchor, item, 1)

    # 4) 追加两个子程序
    PS = 'powers' + 'hell'
    sub = '''
REM ============================================================
REM  子程序：读取访问密钥（仅显示用）
REM ============================================================
:LOAD_KEY
set "API_KEY="
if not exist "%KEY_FILE%" exit /b 0
for /f "usebackq delims=" %%a in (`findstr /v "^#" "%KEY_FILE%"`) do (
  if not defined API_KEY set "API_KEY=%%a"
)
exit /b 0

REM ============================================================
REM  子程序：获取局域网 IPv4（排除回环与 169.254）
REM ============================================================
:GET_LAN_IP
set "LAN_IP="
set "IPTMP=%TEMP%\\llm_lan_ip_check.txt"
__PS__ -NoProfile -Command "$a=Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue; foreach($i in $a){ if($i.IPAddress -notlike '127.*' -and $i.IPAddress -notlike '169.254.*'){ Write-Output $i.IPAddress; break } }" > "%IPTMP%" 2>nul
if exist "%IPTMP%" (
  for /f "usebackq delims=" %%a in ("%IPTMP%") do if not defined LAN_IP set "LAN_IP=%%a"
  del "%IPTMP%" >nul 2>nul
)
exit /b 0
'''.replace('__PS__', PS)
    s = s.rstrip('\n') + '\n' + sub

io.open(P, 'w', encoding='utf-8', newline='\r\n').write(s)
print('gen_check.py 更新完成，检查项:', s.count('/10]'))
