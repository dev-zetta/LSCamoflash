/* DT_NEEDED constructor: real pthread calls before preload initialization. */
#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include <assert.h>
#include <errno.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static pthread_mutex_t mutex = PTHREAD_MUTEX_INITIALIZER;
static int passed;

static void *try_mutex(void *unused)
{
    int result;
    (void)unused;
    result = pthread_mutex_trylock(&mutex);
    if (!result)
        assert(pthread_mutex_unlock(&mutex) == 0);
    return (void *)(uintptr_t)result;
}

__attribute__((constructor))
static void early_dependency(void)
{
    const char *expected = getenv("RTSP_FIXTURE_EXPECT_PROFILE");
    const char *profile = getenv("LSCAMOFLASH_RTSP_PROFILE");
    pthread_t thread;
    void *result = NULL;
    assert(expected);
    /* For both requested profiles this proves actual dependency-before-helper
     * order: the helper constructor consumes this variable when it runs. */
    if (*expected)
        assert(profile && !strcmp(profile, expected));
    else
        assert(!profile);
    assert(getenv("LD_PRELOAD"));

    assert(pthread_mutex_lock(&mutex) == 0);
    assert(pthread_create(&thread, NULL, try_mutex, NULL) == 0);
    assert(pthread_join(thread, &result) == 0);
    assert((uintptr_t)result == EBUSY); /* A returned 0 alone is insufficient. */
    assert(pthread_mutex_unlock(&mutex) == 0);
    assert(pthread_create(&thread, NULL, try_mutex, NULL) == 0);
    assert(pthread_join(thread, &result) == 0 && result == NULL);
    errno = EDOM;
    assert(usleep(10) == 0 && errno == EDOM);
    passed = 1;
    puts("EARLY-DEPENDENCY PASS");
}

int early_dependency_passed(void)
{
    return passed;
}
