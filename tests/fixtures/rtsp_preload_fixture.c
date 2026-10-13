/* Real shared-loader passthrough on unrelated synthetic host/ARM programs. */
#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include <assert.h>
#include <errno.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <unistd.h>

static void *worker(void *argument)
{
    return argument;
}
int main(int argc, char **argv)
{
    pthread_mutex_t mutex = PTHREAD_MUTEX_INITIALIZER;
    pthread_t thread;
    void *result = NULL;
    pid_t child;
    int status;
    /* The synthetic ELF never passes production identity, even with an arm
     * request. No vendor fixed addresses may be accessed. */
    assert(!getenv("LSCAMOFLASH_RTSP_PROFILE"));
    assert(!getenv("LD_PRELOAD"));
    if (argc == 2 && !strcmp(argv[1], "after-exec")) {
        puts("CHILD-PASS");
        return 0;
    }
    assert(pthread_mutex_lock(&mutex) == 0);
    assert(pthread_mutex_unlock(&mutex) == 0);
    errno = EDOM;
    assert(usleep(100) == 0);
    assert(errno == EDOM);
    assert(pthread_create(&thread, NULL, worker, (void *)17) == 0);
    assert(pthread_join(thread, &result) == 0 && result == (void *)17);
    child = fork();
    assert(child >= 0);
    if (!child) {
        const char *qemu = getenv("RTSP_FIXTURE_QEMU");
        const char *sysroot = getenv("RTSP_FIXTURE_SYSROOT");
        if (qemu && sysroot)
            execlp(qemu, qemu, "-cpu", "arm926", "-L", sysroot, argv[0], "after-exec", (char *)NULL);
        else
            execl(argv[0], argv[0], "after-exec", (char *)NULL);
        _exit(127);
    }
    assert(waitpid(child, &status, 0) == child && WIFEXITED(status));
    assert(WEXITSTATUS(status) == 0);
    puts("PASS");
    return 0;
}
