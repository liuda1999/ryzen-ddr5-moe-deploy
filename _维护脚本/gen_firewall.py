# -*- coding: utf-8 -*-
"""生成"开放局域网端口.bat"（需管理员权限，GBK + CRLF）。"""
import io
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "开放局域网端口.bat")

BAT = r'''@echo off
chcp 936 >nul 2>nul
setlocal EnableExtensions
title 开放局域网访问端口 需要管理员权限

REM ============================================================
REM   开放局域网端口.bat
REM   作用：在 Windows 防火墙里放行/取消放行 llama.cpp 服务端口，
REM         让局域网内其它设备能连上本机的大模型服务。
REM   用法：右键本文件 -> 以管理员身份运行
REM ============================================================

set "PORT=35035"
set "RULE=llama.cpp-%PORT%"

net session >nul 2>&1
if errorlevel 1 goto :NO_ADMIN

:MENU
cls
echo ============================================================
echo   llama.cpp 局域网访问 防火墙配置
echo   端口 %PORT%      规则名 %RULE%
echo ============================================================
echo.
netsh advfirewall firewall show rule name="%RULE%" >nul 2>&1
if errorlevel 1 (
  echo   当前状态： 未放行  ^(局域网设备连不上^)
) else (
  echo   当前状态： 已放行
)
echo.
echo ------------------------------------------------------------
echo   1   放行端口 %PORT%  ^(允许局域网访问^)
echo   2   取消放行  ^(删除规则，恢复只允许本机^)
echo   3   查看规则详情
echo   0   退出
echo ------------------------------------------------------------
echo.
set "ACT="
set /p "ACT=  请输入编号 [0] : "
if "%ACT%"=="1" goto :ADD
if "%ACT%"=="2" goto :DEL
if "%ACT%"=="3" goto :SHOW
exit /b 0

:ADD
echo.
echo [信息] 正在添加防火墙入站放行规则...
netsh advfirewall firewall add rule name="%RULE%" dir=in action=allow protocol=TCP localport=%PORT% >nul 2>&1
if errorlevel 1 (
  echo [失败] 添加失败，请确认本窗口是以管理员身份运行的。
) else (
  echo [完成] 已放行 TCP %PORT%。
  echo.
  echo   提醒：放行防火墙只是第一步。服务本身还必须绑定 0.0.0.0
  echo         并且请求要携带 api-key.txt 里的密钥，否则仍然无法调用。
  echo         完整自检请运行：环境检查.bat
)
echo.
pause
goto :MENU

:DEL
echo.
echo [信息] 正在删除防火墙规则...
netsh advfirewall firewall delete rule name="%RULE%" >nul 2>&1
if errorlevel 1 (
  echo [失败] 删除失败或规则本来就不存在。
) else (
  echo [完成] 已删除规则，局域网将无法再连入本端口。
)
echo.
pause
goto :MENU

:SHOW
echo.
netsh advfirewall firewall show rule name="%RULE%"
echo.
pause
goto :MENU

:NO_ADMIN
cls
echo ============================================================
echo   需要管理员权限
echo ============================================================
echo.
echo   本脚本要修改 Windows 防火墙规则，必须以管理员身份运行。
echo.
echo   操作方法：
echo     1. 关闭本窗口
echo     2. 右键 开放局域网端口.bat
echo     3. 选择"以管理员身份运行"
echo.
pause
exit /b 1
'''

io.open(OUT, 'wb').write(BAT.replace('\n', '\r\n').encode('gbk', errors='strict'))
print("written:", OUT)
