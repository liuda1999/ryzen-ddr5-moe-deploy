# -*- coding: utf-8 -*-
"""静态检查 Markdown 文档，专抓「推到 GitHub 才看得出」的排版问题。

用法：
    python _维护脚本\\check_docs.py            # 检查（有硬问题时退出码 1）
    python _维护脚本\\check_docs.py --warn     # 只提示，不返回失败

检查项（硬问题，会导致失败）：
  1. **正文里的 `~` 会被 GitHub 当成删除线**
     —— GFM 里一对单波浪号就会包成 `<del>`（用 GitHub 的渲染接口实测确认，不是错觉）。
        实测例子：`装不下 30B~35B 的全部权重，约 13~16 t/s` 里那两个 ~ 成对，
        于是「35B 的全部权重，约 13」被划掉。
        规则：正文里的 `~` 一律转义成 `\\~`（代码块与行内代码里不转，也不该转）。
  2. 代码围栏 ``` 是否成对（奇数说明有没闭合的块，整篇后面都会变形）

检查项（提示，不影响退出码）：
  3. 文档里引用的 .bat / .md / .txt / .py 文件是否存在
     —— 改名之后最容易漏的就是这里。**历史发布说明（_维护脚本/releases/）跳过**，
        因为它们故意记录当时的旧文件名。

跳过：llama.cpp/ 下的上游文件、_旧脚本备份、_维护脚本/_历史补丁。
"""
import io
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SKIP = ("llama.cpp/", "_旧脚本备份/", "_维护脚本/_历史补丁/")
SKIP_REFS = ("_维护脚本/releases/",)      # 历史发布说明：故意写旧文件名，不做引用检查

FILE_REF = re.compile(r"(?:[\w\-\u4e00-\u9fff]+[\\/])*[\w\-\u4e00-\u9fff]+\.(?:bat|md|txt|py)")
TILDE = re.compile(r"(?<!\\)~")

# 文档里会提到、但**故意**不是现有文件的名字（名字里带旧名/临时文件的说明性文字）
IGNORE_NAMES = {
    # 说明.md §3.14 的「旧名 → 新名」对照表：故意保留旧名
    "启动大模型.bat", "环境检查.bat", "开放局域网端口.bat", "重新编译.bat",
    "使用说明.md", "参数阶梯手册.md", "部署说明.txt", "验收报告.md", "分发包清单.txt",
    # 说明.md 里作为例子出现的临时文件 / 测试脚手架
    "_ps_err.txt", "harness.bat", "in.txt",
}


def md_files():
    out = subprocess.run(["git", "ls-files", "*.md"], cwd=ROOT,
                         capture_output=True).stdout.decode("utf-8").splitlines()
    return [f for f in out if not f.startswith(SKIP)]


def all_repo_files():
    out = subprocess.run(["git", "ls-files"], cwd=ROOT,
                         capture_output=True).stdout.decode("utf-8").splitlines()
    return set(os.path.basename(x) for x in out)


def strip_code(text):
    """去掉代码围栏与行内代码，返回 [(行号, 正文)] —— 检查只看正文。"""
    out = []
    fence = False
    for i, ln in enumerate(text.split("\n"), 1):
        if ln.lstrip().startswith("```"):
            fence = not fence
            continue
        if fence:
            continue
        out.append((i, re.sub(r"`[^`]*`", "", ln)))
    return out


def check_tilde(name, text):
    bad = []
    para = []

    def flush(para):
        # 只数「未转义」的 ~：\~ 是安全的，不算。
        # 同一个段落（或同一格）里出现 >= 2 个就会两两配对成删除线 —— 不看行数，
        # 一行里塞两个同样会出问题。
        total = sum(len(TILDE.findall(body)) for _, body in para)
        if total >= 2:
            for ln, body in para:
                if TILDE.search(body):
                    bad.append("%s 第 %d 行：正文里有未转义的 ~（会与同段另一个配对成删除线）：%s"
                               % (name, ln, body.strip()[:60]))

    for ln, body in strip_code(text):
        if not body.strip():
            flush(para); para = []
            continue
        if body.lstrip().startswith("|"):    # 表格：每格单独看
            flush(para); para = []
            for cell in body.split("|"):
                if len(TILDE.findall(cell)) >= 2:
                    bad.append("%s 第 %d 行：表格单元格里有未转义的 ~：%s"
                               % (name, ln, cell.strip()[:60]))
            continue
        para.append((ln, body))
    flush(para)
    return bad


def check_fence(name, text):
    n = sum(1 for ln in text.split("\n") if ln.lstrip().startswith("```"))
    if n % 2:
        return ["%s：代码围栏 ``` 有 %d 个（奇数，说明有没闭合的代码块）" % (name, n)]
    return []


def check_file_refs(name, text, repo_names):
    warns = []
    for ref in sorted(set(FILE_REF.findall(text))):
        rel = ref.replace("\\", "/")
        if os.path.exists(os.path.join(ROOT, rel)):
            continue
        base = rel.split("/")[-1]
        if base in repo_names or base in IGNORE_NAMES:   # 同名文件在别的目录 / 已知的说明性引用
            continue
        warns.append("%s：引用了仓库里找不到的文件 %s" % (name, ref))
    return warns


def main():
    hard, warn = [], []
    repo_names = all_repo_files()
    files = md_files()
    for f in files:
        text = io.open(os.path.join(ROOT, f.replace("/", os.sep)), encoding="utf-8").read()
        hard += check_tilde(f, text)
        hard += check_fence(f, text)
        if not f.startswith(SKIP_REFS):
            warn += check_file_refs(f, text, repo_names)

    if warn:
        print("提示（不影响退出码）%d 条：" % len(warn))
        for w in warn:
            print("  ·", w)
        print()
    if hard:
        print("发现 %d 个硬问题：" % len(hard))
        for p in hard:
            print("  -", p)
        sys.exit(0 if "--warn" in sys.argv else 1)
    print("检查通过：%d 个 Markdown 文档 —— 正文无未转义的 ~（不会出现删除线）、代码围栏成对。"
          % len(files))


if __name__ == "__main__":
    main()
