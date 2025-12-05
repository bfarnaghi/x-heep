#include <stdio.h>
#include <stdint.h>
#include <inttypes.h>

// volatile to prevent compiler optimization removing the load asm instruction
__attribute__((section(".xheep_user_data"))) volatile uint32_t* user_pointer_to_monitor;

// 2048 bytes stack for user mode - in xheep_user_data since xheep_user_stack section doesn't exist
__attribute__((section(".xheep_user_data"))) unsigned char user_stack[2048]; // 2KB stack

__attribute__((section(".xheep_user_code")))
void user_mode_entry() {
    // In U-mode: esegui eventuale accesso dati consentito
#ifndef PLAIN
    uint32_t value = *user_pointer_to_monitor; // Handler in "x-heep/sw/device/lib/runtime/handler.c"
    *user_pointer_to_monitor = *user_pointer_to_monitor + 1;
#endif

    // Prepara i registri per la syscall:
    // a7 = syscall_id (0 = exit), a0 = puntatore passato all'handler M-mode
    uint32_t syscall_id = 0;  // SYSCALL_EXIT
    volatile uint32_t* ptr = user_pointer_to_monitor;
    asm volatile (
        "mv a7, %0;\n"
        "mv a0, %1;\n"
        "ecall\n"
        :: "r"(syscall_id), "r"(ptr)
        : "a7", "a0", "memory");
}

static inline uint64_t read_mcycle(void) {
#if __riscv_xlen == 32
    uint32_t hi, lo;
    do {
        asm volatile("csrr %0, mcycleh" : "=r"(hi));
        asm volatile("csrr %0, mcycle"  : "=r"(lo));
        uint32_t hi2;
        asm volatile("csrr %0, mcycleh" : "=r"(hi2));
        if (hi == hi2) return (((uint64_t)hi) << 32) | lo;
    } while (1);
#else
    uint64_t val;
    asm volatile("csrr %0, mcycle" : "=r"(val));
    return val;
#endif
}

static inline uint64_t read_minstret(void) {
#if __riscv_xlen == 32
    uint32_t hi, lo;
    do {
        asm volatile("csrr %0, minstreth" : "=r"(hi));
        asm volatile("csrr %0, minstret"  : "=r"(lo));
        uint32_t hi2;
        asm volatile("csrr %0, minstreth" : "=r"(hi2));
        if (hi == hi2) return (((uint64_t)hi) << 32) | lo;
        hi = hi2;
    } while (1);
#else
    uint64_t val;
    asm volatile("csrr %0, minstret" : "=r"(val));
    return val;
#endif
}

void switch_to_user_mode() {
    asm volatile (
        "la t0, user_mode_entry    \n"  // Load user entry point function address
        "csrw mepc, t0             \n"  // Set Machine Exception Program Counter (MEPC) to the first User Function to jump to

        "la sp, user_stack         \n"  // Set SP for user mode
        "li t2, 0x800              \n"  // Load value 2048 in t2. !WARNING!: This value must be arranged according to stack size defined in the linker file
        "add sp, sp, t2            \n"  // Set SP to the top of the user stack

        "csrr t1, mstatus          \n"  // Read mstatus
        "li t2, ~(3 << 11)         \n"  // Set MPP to 00 (bits 12:11 <== {[!(3 b10 => 11 b2) => 00 b2] << 11, left shift 11 positions})
        "and t1, t1, t2            \n"  // AND logical operation to clear MPP bits
        "csrw mstatus, t1          \n"  // Write back to mstatus

        "mret                      \n"  // Return from machine mode to user mode
    );
}

void pmp_setup() {
    // ==============================================================
    // STRATEGY:
    // - M-mode must be able to access everywhere (no L bit on its regions)
    // - U-mode is limited by PMP entries with explicit permissions
    // ==============================================================
    uint64_t cycles_start, instret_start, cycles_end, instret_end;

    // abilita tutti i contatori (CY/IR incl.)
    asm volatile("csrw mcountinhibit, zero\n");
    asm volatile("fence" ::: "memory");
    instret_start = read_minstret();
    cycles_start = read_mcycle();

    // MACHINE CODE ==> PMP0: [0x000000, 0x007FFF] (code)
    // M-mode: free access (no L bit, bypasses PMP)
    // U-mode: NO access (no R/W/X permissions)
    asm volatile("csrw pmpaddr0, %0" :: "r"(0x00008000 >> 2));
    uint8_t pmp0cfg = (1 << 3);  // TOR

#ifdef MRC
    uintptr_t pmpaddr0_MRC;
    asm volatile (
        "csrr  %0, pmpaddr0\n\r\t" : "=r"(pmpaddr0_MRC)
    );
    if (!pmpaddr0_MRC != !pmp0cfg) {
        asm volatile("fence" ::: "memory");
        cycles_end = read_mcycle();
        instret_end = read_minstret();
        printf("cyc: %lu, ins: %lu\n\r", cycles_end - cycles_start, instret_end - instret_start);
        printf("[MRC] MRC triggered! pmpaddr0: 0x%x, pmp0cfg: 0x%x\n\r", pmpaddr0_MRC, pmp0cfg);
        exit(1);
    }
#endif

    // USER CODE ==> PMP1: [0x008000, 0x00BFFF] (user_code)
    // M-mode: free access (no L bit, bypasses PMP)
    // U-mode: can execute (has X bit)
#ifdef IMC
    asm volatile("nop");
#else
    asm volatile("csrw pmpaddr1, %0" :: "r"(0x0000C000 >> 2));
#endif

#ifdef IMC
    uint8_t pmp1cfg = (1 << 3);  // TOR
#else
    uint8_t pmp1cfg = (1 << 2) | (1 << 3);  // X | TOR
#endif
    
    // MACHINE DATA ==> PMP2: [0x00C000, 0x013FFF] (data)
    // M-mode: free access (no L bit, bypasses PMP)
    // U-mode: NO access (no R/W/X permissions)
#if defined(PEA) || defined(DIs) || defined(TIs) || defined(MRC)
    asm volatile("nop");
#else
    asm volatile("csrw pmpaddr2, %0" :: "r"(0x00014000 >> 2));
#endif

#ifdef IMC
    uint8_t pmp2cfg = (1 << 2) | (1 << 3);  // X | TOR
#else
    uint8_t pmp2cfg = (1 << 3);  // TOR
#endif

#ifdef MRC
    uintptr_t pmpaddr2_MRC;
    asm volatile (
        "csrr  %0, pmpaddr2\n\r\t" : "=r"(pmpaddr2_MRC)
    );
    if (!pmpaddr2_MRC != !pmp2cfg) {
        asm volatile("fence" ::: "memory");
        cycles_end = read_mcycle();
        instret_end = read_minstret();
        printf("cyc: %lu, ins: %lu\n\r", cycles_end - cycles_start, instret_end - instret_start);
        printf("[MRC] MRC triggered! pmpaddr2: 0x%lx, pmp2cfg: 0x%x\n\r", pmpaddr2_MRC, pmp2cfg);
        exit(1);
    }
#endif

    // USER DATA ==> PMP3: [0x014000, 0x017FFF] (user_data)
    // M-mode: free access (no L bit, bypasses PMP)
    // U-mode: can read/write (has R|W bits)
    asm volatile("csrw pmpaddr3, %0" :: "r"(0x00018000 >> 2));
    uint8_t pmp3cfg = (1 << 0) | (1 << 1) | (1 << 3);  // R | W | TOR

    uint32_t pmpcfg0_val = pmp0cfg | (pmp1cfg << 8) | (pmp2cfg << 16) | (pmp3cfg << 24);
    asm volatile("csrw pmpcfg0, %0" :: "r"(pmpcfg0_val));

#ifdef DIs
    uintptr_t pmpaddr0_DIs_1, pmpaddr0_DIs_2;
    uintptr_t pmpaddr2_DIs_1, pmpaddr2_DIs_2;
    asm volatile ("csrr  %0, pmpaddr0\n\r\t" : "=r"(pmpaddr0_DIs_1));
    asm volatile ("csrr  %0, pmpaddr2\n\r\t" : "=r"(pmpaddr2_DIs_1));
    asm volatile("csrw pmpaddr0, %0" :: "r"(0x00008000 >> 2));
    asm volatile("csrw pmpaddr2, %0" :: "r"(0x0000C000 >> 2));
    asm volatile ("csrr  %0, pmpaddr0\n\r\t" : "=r"(pmpaddr0_DIs_2));
    asm volatile ("csrr  %0, pmpaddr2\n\r\t" : "=r"(pmpaddr2_DIs_2));
    if ((pmpaddr0_DIs_1 != pmpaddr0_DIs_2) || (pmpaddr2_DIs_1 != pmpaddr2_DIs_2)) {
        asm volatile("fence" ::: "memory");
        cycles_end = read_mcycle();
        instret_end = read_minstret();
        printf("cyc: %lu, ins: %lu\n\r", cycles_end - cycles_start, instret_end - instret_start);
        printf("[DIs] DIs triggered! pmpaddr0_1: 0x%lx, pmpaddr0_2: 0x%lx, pmpaddr2_1: 0x%lx, pmpaddr2_2: 0x%lx,\n\r", pmpaddr0_DIs_1, pmpaddr0_DIs_2, pmpaddr2_DIs_1, pmpaddr2_DIs_2);
        exit(1);
    }
#endif

#ifdef TIs
    uintptr_t pmpaddr0_TIs_1, pmpaddr0_TIs_2, pmpaddr0_TIs_3;
    uintptr_t pmpaddr2_TIs_1, pmpaddr2_TIs_2, pmpaddr2_TIs_3;
    asm volatile ("csrr  %0, pmpaddr0\n\r\t" : "=r"(pmpaddr0_TIs_1));
    asm volatile ("csrr  %0, pmpaddr2\n\r\t" : "=r"(pmpaddr2_TIs_1));
    asm volatile("csrw pmpaddr0, %0" :: "r"(0x00008000 >> 2));
    asm volatile("csrw pmpaddr2, %0" :: "r"(0x0000C000 >> 2));
    asm volatile ("csrr  %0, pmpaddr0\n\r\t" : "=r"(pmpaddr0_TIs_2));
    asm volatile ("csrr  %0, pmpaddr2\n\r\t" : "=r"(pmpaddr2_TIs_2));
    asm volatile("csrw pmpaddr0, %0" :: "r"(0x00008000 >> 2));
    asm volatile("csrw pmpaddr2, %0" :: "r"(0x0000C000 >> 2));
    asm volatile ("csrr  %0, pmpaddr0\n\r\t" : "=r"(pmpaddr0_TIs_3));
    asm volatile ("csrr  %0, pmpaddr2\n\r\t" : "=r"(pmpaddr2_TIs_3));
    if (((pmpaddr0_TIs_1 != pmpaddr0_TIs_2) || (pmpaddr0_TIs_2 != pmpaddr0_TIs_3)) || ((pmpaddr2_TIs_1 != pmpaddr2_TIs_2) || (pmpaddr2_TIs_2 != pmpaddr2_TIs_3))) {
        asm volatile("fence" ::: "memory");
        cycles_end = read_mcycle();
        instret_end = read_minstret();
        printf("cyc: %lu, ins: %lu\n\r", cycles_end - cycles_start, instret_end - instret_start);
        printf("[TIs] TIs triggered! pmpaddr0_1: 0x%lx, pmpaddr0_2: 0x%lx, pmpaddr2_1: 0x%lx, pmpaddr2_2: 0x%lx,\n\r", pmpaddr0_TIs_1, pmpaddr0_TIs_2, pmpaddr2_TIs_1, pmpaddr2_TIs_2);
        exit(1);
    }
#endif

    // Ensure all instructions are retired before reading counters
    asm volatile("fence" ::: "memory");
    cycles_end = read_mcycle();
    instret_end = read_minstret();
    printf("cyc: %lu, ins: %lu\n\r", cycles_end - cycles_start, instret_end - instret_start);

    //printf("[MACHINE MODE] PMP configured\n\r");
}

int main() {
    //printf("[MACHINE MODE] Booting...\n\r");
    
    int monitor_variable = 0xdeadbeef;
    printf("m_var %p = %x\n\r", &monitor_variable, monitor_variable);

    user_pointer_to_monitor = (volatile uint32_t*)&monitor_variable;

    pmp_setup();
    
    //printf("[MACHINE MODE] Switching to user mode...\n\r");
    switch_to_user_mode();
    
    // Should never reach here - user mode exits via syscall
    printf("[MACHINE MODE] ERROR: Returned from user mode unexpectedly\n\r");
    return 1;
}