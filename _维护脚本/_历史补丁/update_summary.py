# -*- coding: utf-8 -*-
"""更新部署说明.txt 中的脚本引用为新的中文命名。"""
import io, re

P = r"E:\llm-cpp\部署说明.txt"
s = io.open(P, encoding='utf-8').read()

old_start = "  快捷启动（推荐，工作区根目录）："
old_end = "  下一阶段：大模型由你提供；届时放入模型并配置启动参数即可推理。"
i = s.find(old_start)
j = s.find(old_end)
assert i > 0 and j > i, (i, j)

new = """  快捷开关（推荐，工作区根目录，全中文命名）：
    E:\\llm-cpp\\启动大模型.bat              二合一开关：未运行则启动，已运行则关闭
                                        （双击即可，按提示选档位，默认实用档）
    E:\\llm-cpp\\启动大模型.bat start 2      直接以实用档（16K/24 线程）启动
    E:\\llm-cpp\\启动大模型.bat stop         关闭服务并释放内存
    E:\\llm-cpp\\启动大模型.bat restart 3    以长文档档（24K/24 线程）重启
    E:\\llm-cpp\\启动大模型.bat status       只看状态（PID / 内存 / 档位 / 地址）
    E:\\llm-cpp\\启动大模型.bat check        只做环境与安全检查

    E:\\llm-cpp\\环境检查.bat                全量体检，并给出各档位内存可行性
    E:\\llm-cpp\\参数阶梯手册.md             参数阶梯手册（全部实测档位，改配置前先看它）

  启动脚本内置的检查（出现 [失败] 会直接阻止启动）：
    1  可执行程序 llama-server.exe / llama-cli.exe
    2  依赖 DLL：llama / llama-common / ggml / ggml-base
    3  CPU 后端变体：确认 icelake(AVX-512+VNNI+VBMI) 生效；
       若发现 cascadelake 抢占会自动改名为 .disabled
    4  模型文件存在且大小合理（完整约 21.3 GB）
    5  多模态投影 mmproj（缺失只警告，退化为纯文本）
    6  端口 35035 是否被别的进程占用（并打印占用者进程名）
    7  磁盘剩余空间（低于 2 GB 拒绝启动）
    8  是否已有重复实例（防止重复启动）
    9  可用内存是否够本档位：不够直接拒绝，偏紧时二次确认

  重新编译（你本机，Visual Studio 生成器）：
    双击  E:\\llm-cpp\\重新编译.bat
    产物  E:\\llm-cpp\\llama.cpp\\build-vs\\bin\\Release\\

  旧版英文脚本已归档：E:\\llm-cpp\\_旧脚本备份\\（llm.bat / check-env.bat / run-llama-*.bat）

"""
s = s[:i] + new + s[j:]

# 修正文件内其它旧名引用
s = s.replace("E:\\llm-cpp\\CONFIG-TIERS.md", "E:\\llm-cpp\\参数阶梯手册.md")
s = s.replace("CONFIG-TIERS.md / matrix_results.csv", "参数阶梯手册.md / matrix_results.csv")
s = s.replace("详见 CONFIG-TIERS.md", "详见 参数阶梯手册.md")

io.open(P, 'w', encoding='utf-8', newline='\r\n').write(s)
print("updated:", P)
