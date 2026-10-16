/* LSC 3225722 / SZ F26312 / YYOS 14.1.5 kernel compatibility only.
 * This kernel returns success without writing ARM time64 syscall buffers.
 * Link this object before musl libc for an already exact-profile-guarded tool.
 * Preserve the requested clock, including CLOCK_MONOTONIC; never use wall time
 * to implement a deadline. This is not a general replacement libc interface.
 */
#define _GNU_SOURCE
#include <errno.h>
#include <stdint.h>
#include <time.h>
#include <unistd.h>

#if !defined(__linux__) || !defined(__arm__) || __SIZEOF_LONG__ != 4
#error "YYOS legacy clock compatibility requires 32-bit ARM Linux"
#endif

/* ARM EABI kernel ABI: two signed 32-bit longs, independent of libc time_t. */
struct yyos_kernel_timespec32 {
    int32_t seconds;
    int32_t nanoseconds;
};
_Static_assert(sizeof(struct yyos_kernel_timespec32) == 8,
               "unexpected legacy ARM kernel timespec size");

static int yyos_read_clock(long number, clockid_t clock, struct timespec *output,
                           int resolution)
{
    struct yyos_kernel_timespec32 kernel = {-1, -1};
    if (!output && !resolution) {
        errno = EFAULT;
        return -1;
    }
    if (syscall(number, clock, &kernel) < 0)
        return -1;
    /* Reject the success-without-output failure observed in the time64 stub. */
    if (kernel.seconds < 0 || kernel.nanoseconds < 0
            || kernel.nanoseconds >= 1000000000) {
        errno = EIO;
        return -1;
    }
    if (output) {
        output->tv_sec = (time_t)kernel.seconds;
        output->tv_nsec = (long)kernel.nanoseconds;
    }
    return 0;
}

int clock_gettime(clockid_t clock, struct timespec *output)
{
    return yyos_read_clock(263, clock, output, 0);
}

int clock_getres(clockid_t clock, struct timespec *output)
{
    return yyos_read_clock(264, clock, output, 1);
}
