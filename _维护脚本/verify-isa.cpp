// 极小验证程序：查询 llama.cpp 运行时已启用的后端与指令集（CPU ISA）。
// 不加载任何模型、不做基准测试，仅调用官方 API：
//   ggml_backend_load_all()  -> 注册/加载各后端（含 CPU）
//   llama_print_system_info() -> 返回 "Backend : FEATURE = 1 | ..."
#include <windows.h>
#include <cstdio>

typedef void (*load_all_t)();
typedef const char * (*sysinfo_t)();

int main() {
    // llama.dll 位于本可执行文件同目录；加载时会一并解析 ggml 依赖
    HMODULE hl = LoadLibraryA("llama.dll");
    if (!hl) { printf("[ERR] LoadLibrary llama.dll failed (%lu)\n", GetLastError()); return 1; }

    HMODULE hg = GetModuleHandleA("ggml.dll");
    if (!hg) hg = LoadLibraryA("ggml.dll");
    if (hg) {
        load_all_t load_all = (load_all_t)GetProcAddress(hg, "ggml_backend_load_all");
        if (load_all) load_all();
    }

    sysinfo_t si = (sysinfo_t)GetProcAddress(hl, "llama_print_system_info");
    if (!si) { printf("[ERR] symbol llama_print_system_info not found\n"); return 1; }

    printf("%s\n", si());
    return 0;
}
