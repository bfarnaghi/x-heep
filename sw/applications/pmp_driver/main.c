#include <stdio.h>
#include <stdint.h>

void run_secure_inference();


__attribute__((section(".xheep_user_data"))) char user_message[] = "Hello from U-mode!";
__attribute__((section(".xheep_user_data"))) uint8_t inference_input[4]= {1, 0, 3, 5};
__attribute__((section(".xheep_user_data"))) uint8_t inference_output[1];

__attribute__((section(".xheep_user_stack"))) unsigned char user_stack[4096];


__attribute__((section(".xheep_user_code")))
static inline void user_printf(const char *msg) {
    register uint32_t syscall_id asm("a7") = 2;  // SYSCALL_PRINT
    register const char *msg_ptr asm("a0") = msg;

    asm volatile (
        "ecall"
        :: "r" (syscall_id), "r" (msg_ptr)
        : "memory"
    );
}
__attribute__((section(".xheep_user_code")))
void user_mode_entry() {

    // Run secure inference
    register uint32_t syscall_id asm("a7") = 1;
    asm volatile("ecall" :: "r"(syscall_id));

    user_printf("Hello!");

    // Check result
    uint8_t result = inference_output[0];

    run_secure_inference();

    while (1); // Loop to prevent returning
}


void run_secure_inference() {
    uint8_t sum = 0;
    for (int i = 0; i < 4; i++) sum += inference_input[i];
    inference_output[0] = sum; // Return simple result for demo
    printf("[M] Result = %d\n", inference_output[0]);
}


void pmp_setup() {
    asm volatile("csrw pmpaddr0, %0" :: "r"(0x010000 >> 2));
    asm volatile("csrw pmpaddr1, %0" :: "r"(0x020000 >> 2));

    uint8_t cfg0 = (1 << 2) | (1 << 3);             // X | TOR (M-mode)
    uint8_t cfg1 = (1 << 0) | (1 << 1) | (1 << 2) | (1 << 3); // R | W | X | TOR (U-mode)

    uint32_t pmpcfg = cfg0 | (cfg1 << 8);
    asm volatile("csrw pmpcfg0, %0" :: "r"(pmpcfg));
}


void switch_to_user_mode() {
    asm volatile (
        "la t0, user_mode_entry    \n"  // Load user function address
        "csrw mepc, t0             \n"  // Set MEPC 

        "la sp, user_stack         \n"  
        "li t2, 4096               \n"  
        "add sp, sp, t2            \n"  

        "csrr t1, mstatus          \n"
        "li t2, ~(3 << 11)         \n"  // Clear MPP (bits 12:11)
        "and t1, t1, t2            \n"
        "csrw mstatus, t1          \n"

        "mret                      \n"  
    );
}


int main() {
    printf("[Boot]\n");
    pmp_setup();
    switch_to_user_mode();
    printf("[M] ERROR\n");
    return 0;
}


