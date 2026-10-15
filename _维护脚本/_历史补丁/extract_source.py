import zipfile, os

SRC = os.environ.get("SRC_WIN", "/tmp/llama.cpp.zip")
DST = os.environ.get("DST_WIN", "/e/llm-cpp/llama.cpp")

os.makedirs(DST, exist_ok=True)
with zipfile.ZipFile(SRC) as z:
    for info in z.infolist():
        parts = info.filename.split("/")
        if len(parts) <= 1:
            continue
        rel = "/".join(parts[1:])
        if not rel:
            continue
        target = os.path.join(DST, rel)
        if info.is_dir():
            os.makedirs(target, exist_ok=True)
        else:
            parent = os.path.dirname(target)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with z.open(info) as f, open(target, "wb") as out:
                out.write(f.read())
print("Extracted to", DST)
print("Top entries:", sorted(os.listdir(DST))[:40])
