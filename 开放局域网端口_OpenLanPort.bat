@echo off
chcp 936 <nul >nul 2>nul
setlocal EnableExtensions
title 开放局域网访问端口 需要管理员权限

REM ============================================================
REM   开放局域网端口_OpenLanPort.bat
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
echo   llama.cpp 局域网访问 / LAN access 防火墙配置 / Firewall setup
echo   端口/Port %PORT%      规则名/Rule %RULE%
echo ============================================================
echo.
netsh advfirewall firewall show rule name="%RULE%" >nul 2>&1
if errorlevel 1 (
  echo   当前状态/STATUS：未放行 / BLOCKED  ^(局域网设备连不上 / other devices cannot connect^)
) else (
  echo   当前状态/STATUS：已放行 / ALLOWED
)
echo.
echo ------------------------------------------------------------
echo   1   放行端口 / Allow port %PORT%  ^(允许局域网访问 / allow LAN access^)
echo   2   取消放行 / Remove rule  ^(删除规则，恢复只允许本机 / local-only again^)
echo   3   查看规则详情 / Show rule details
echo   0   退出 / Exit
echo ------------------------------------------------------------
echo.
set "ACT="
set /p "ACT=  请输入编号/Enter number [0] : "
if "%ACT%"=="1" goto :ADD
if "%ACT%"=="2" goto :DEL
if "%ACT%"=="3" goto :SHOW
exit /b 0

:ADD
echo.
echo [信息/INFO] 正在添加防火墙入站放行规则 / adding inbound firewall rule...
netsh advfirewall firewall add rule name="%RULE%" dir=in action=allow protocol=TCP localport=%PORT% >nul 2>&1
if errorlevel 1 (
  echo [失败/FAIL] 添加失败 / failed，请确认本窗口是以管理员身份运行的 / run this window as administrator.
) else (
  echo [完成/DONE] 已放行 / allowed TCP %PORT%.
  echo.
  echo   提醒/NOTE：放行防火墙只是第一步 / the firewall rule is only step one. 服务本身还必须绑定 / the service must also bind 0.0.0.0
  echo         并且请求要携带 / and requests must carry the key from api-key.txt，否则仍然无法调用 / otherwise calls fail.
  echo         完整自检请运行 / for a full check run：环境检查_EnvCheck.bat
)
echo.
pause
goto :MENU

:DEL
echo.
echo [信息/INFO] 正在删除防火墙规则 / removing firewall rule...
netsh advfirewall firewall delete rule name="%RULE%" >nul 2>&1
if errorlevel 1 (
  echo [失败/FAIL] 删除失败或规则本来就不存在 / removal failed or the rule did not exist.
) else (
  echo [完成/DONE] 已删除规则 / rule removed，局域网将无法再连入本端口 / LAN can no longer reach this port.
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
echo   需要管理员权限 / Administrator rights required
echo ============================================================
echo.
echo   本脚本要修改 Windows 防火墙规则 / this script edits firewall rules，必须以管理员身份运行 / it must run as administrator.
echo.
echo   操作方法 / How to do it：
echo     1. 关闭本窗口 / close this window
echo     2. 右键 / right-click 开放局域网端口_OpenLanPort.bat
echo     3. 选择 / choose "以管理员身份运行" / Run as administrator
echo.
pause
exit /b 1
