// 只读 CPUID 特性位（不读取 CPU 型号字符串），用于确认 AVX-512 各扩展的实际可用性
#include <stdio.h>
#include <intrin.h>

int main(void) {
    int regs[4] = {0};
    __cpuid(regs, 0);
    int maxleaf = regs[0];
    printf("max_leaf=%d\n", maxleaf);
    if (maxleaf < 7) {
        printf("CPUID leaf 7 unsupported\n");
        return 0;
    }

    __cpuidex(regs, 7, 0);
    unsigned ebx = (unsigned)regs[1], ecx = (unsigned)regs[2], edx = (unsigned)regs[3];
    printf("[leaf 7 subleaf 0]\n");
    printf("  AVX512F      (ebx16) = %d\n", (ebx >> 16) & 1);
    printf("  AVX512DQ     (ebx17) = %d\n", (ebx >> 17) & 1);
    printf("  AVX512IFMA   (ebx21) = %d\n", (ebx >> 21) & 1);
    printf("  AVX512CD     (ebx28) = %d\n", (ebx >> 28) & 1);
    printf("  AVX512BW     (ebx30) = %d\n", (ebx >> 30) & 1);
    printf("  AVX512VL     (ebx31) = %d\n", (ebx >> 31) & 1);
    printf("  AVX512VBMI   (ecx1)  = %d\n", (ecx >> 1) & 1);
    printf("  AVX512VBMI2  (ecx6)  = %d\n", (ecx >> 6) & 1);
    printf("  AVX512VNNI   (ecx11) = %d\n", (ecx >> 11) & 1);
    printf("  AVX512BITALG (ecx12) = %d\n", (ecx >> 12) & 1);
    printf("  AVX512VPOPCNTDQ (ecx14) = %d\n", (ecx >> 14) & 1);

    __cpuidex(regs, 7, 1);
    unsigned eax1 = (unsigned)regs[0];
    printf("[leaf 7 subleaf 1]\n");
    printf("  AVX512BF16   (eax5)  = %d\n", (eax1 >> 5) & 1);

    printf("[leaf 7 subleaf 0 edx]\n");
    printf("  AMX-BF16     (edx22) = %d\n", (edx >> 22) & 1);
    printf("  AMX-TILE     (edx24) = %d\n", (edx >> 24) & 1);
    printf("  AMX-INT8     (edx25) = %d\n", (edx >> 25) & 1);
    return 0;
}
