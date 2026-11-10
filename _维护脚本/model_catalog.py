# -*- coding: utf-8 -*-
"""官方模型文件的精确字节数 —— 全项目唯一事实源。

来源：unsloth/Qwen3.6-35B-A3B-GGUF 官方发布文件，以 hf-mirror.com 直链
响应头 Content-Length 为准（2026-11-11 复核）。

为什么需要这个文件：
  分发包清单曾经直接读【本机模型文件】的大小，而本机那两份是早期版本
  （Q4_K_M 21,233,608,512 B、mmproj 902,822,528 B），与官方发布值分别差了
  900,920,480 B（约 859 MiB）和 96 B。结果任何按 README 下载官方模型的用户
  跑 verify_package.py，都会被判「分发包不完整，建议重新拷贝」。数值必须由
  单一来源统一，且清单只能把它当作参考值，不能当作包完整性的判据。

引用方（改这里必须全部同步，CI 的 check_manifest.py 会逐项核对）：
  - _维护脚本/make_manifest.py          写入分发包清单（参考值）
  - _维护脚本/check_manifest.py         CI 交叉核对
  - _维护脚本/gen_toggle.py             -> 启动大模型_StartModel.bat 的 DL_BYTES
  - llama.cpp/models/下载模型.md        第四节「精确字节数」表
  - README.md / 使用说明_UserGuide.md   里的 GB 数是约数，不参与精确核对
"""

# 文件名 -> 官方发布的精确字节数
MODELS = {
    "Qwen3.6-35B-A3B-UD-Q4_K_M.gguf": 22134528992,
    "Qwen3.6-35B-A3B-UD-IQ3_S.gguf": 13676723168,
    "mmproj-BF16.gguf": 902822624,
}

# 主模型二选一；mmproj 只在需要看图时下载（README 明确说可选）
PRIMARY_MODELS = (
    "Qwen3.6-35B-A3B-UD-Q4_K_M.gguf",
    "Qwen3.6-35B-A3B-UD-IQ3_S.gguf",
)

# 判定「明显截断」的相对阈值：实际体积不足官方值一半才算下载不完整。
# 不能用固定的 1 GiB —— mmproj-BF16.gguf 官方就只有 902,822,624 B
# （约 0.84 GiB），固定阈值会把合法文件判成损坏。
# verify_package.py 因需在目标机自包含运行，独立写了同值常量；
# check_manifest.py 会核对两边一致。
TRUNCATE_RATIO = 0.5

# 清单里的路径分隔符固定为反斜杠。用 chr(92) 拼，避免源码里出现
# 容易看错的反斜杠转义（清单是 Windows cmd 生态，路径一直用反斜杠）。
SEP = chr(92)
MODEL_DIR = SEP.join(("llama.cpp", "models"))


def model_rel(name):
    """返回清单里使用的相对路径，例如 llama.cpp\\models\\xxx.gguf。"""
    return MODEL_DIR + SEP + name
