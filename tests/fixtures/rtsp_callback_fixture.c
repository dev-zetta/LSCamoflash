/* Synthetic callbacks/state only: this program never loads vendor firmware. */
#include <pthread.h>
#include <unistd.h>
#include <dlfcn.h>
static void *fixture_dlsym(void *, const char *);
#define dlsym fixture_dlsym
#define usleep fixture_usleep
#define pthread_mutex_lock fixture_lock
#define pthread_join fixture_join
#define CAMOFLASH_RTSP_TEST
#include "../../SOURCE/src/contrib/rtsp-callback/rtsp_callback.c"
#undef usleep
#undef pthread_mutex_lock
#undef pthread_join
#undef dlsym
#include <assert.h>
#include <stdio.h>

static pthread_mutex_t fake_mutex = PTHREAD_MUTEX_INITIALIZER;
static uint32_t fake_initialized = 1;
static void *fake_handles[4] = {(void *)1, (void *)2, (void *)3, (void *)4};
static video_cb fake_slots[2];
static int sends, last_channel, last_length, sleeps, locks, joins, setter_calls;
static void *last_data;
static uint64_t last_timestamp;
static useconds_t last_delay;
static int fake_clock_failure, fake_busy;
static pthread_mutex_t observations = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t observation_changed = PTHREAD_COND_INITIALIZER;
static int block_send, send_entered, release_send, stop_entered, stop_completed;
static time_t fake_seconds;

static int mock_sleep(useconds_t delay)
{
    ++sleeps;
    last_delay = delay;
    errno = EINTR;
    return -1;
}
static int mock_lock(pthread_mutex_t *mutex)
{
    pthread_mutex_lock(&observations);
    ++locks;
    pthread_mutex_unlock(&observations);
    return pthread_mutex_lock(mutex);
}
static int mock_trylock(pthread_mutex_t *mutex)
{
    return fake_busy ? EBUSY : pthread_mutex_trylock(mutex);
}
static int mock_join(pthread_t thread, void **result)
{
    (void)thread;
    ++joins;
    if (result)
        *result = (void *)17;
    return 23;
}
static int mock_clock(clockid_t id, struct timespec *value)
{
    assert(id == CLOCK_MONOTONIC);
    if (fake_clock_failure)
        return -1;
    value->tv_sec = fake_seconds;
    value->tv_nsec = 0;
    return 0;
}
static int mock_set(int channel, video_cb callback)
{
    assert(channel == 0 || channel == 1);
    assert(callback); /* Publication must never be undone while encoding. */
    ++setter_calls;
    fake_slots[channel] = callback;
    return 0;
}
static void mock_send(int channel, void *data, int length, uint64_t timestamp)
{
    ++sends;
    last_channel = channel;
    last_data = data;
    last_length = length;
    last_timestamp = timestamp;
    if (block_send) {
        pthread_mutex_lock(&observations);
        send_entered = 1;
        pthread_cond_broadcast(&observation_changed);
        while (!release_send)
            pthread_cond_wait(&observation_changed, &observations);
        pthread_mutex_unlock(&observations);
    }
}
static void *fixture_dlsym(void *handle, const char *name)
{
    (void)handle;
    if (!strcmp(name, "usleep")) return mock_sleep;
    if (!strcmp(name, "pthread_mutex_lock")) return mock_lock;
    if (!strcmp(name, "pthread_mutex_unlock")) return pthread_mutex_unlock;
    if (!strcmp(name, "pthread_mutex_trylock")) return mock_trylock;
    if (!strcmp(name, "pthread_join")) return mock_join;
    return NULL;
}
static void setup(void)
{
    unsigned i;
    next_usleep = mock_sleep;
    next_lock = mock_lock;
    next_unlock = pthread_mutex_unlock;
    next_trylock = mock_trylock;
    next_join = mock_join;
    get_time = mock_clock;
    set_callback = mock_set;
    send_video = mock_send;
    stock_mutex = &fake_mutex;
    stock_initialized = &fake_initialized;
    for (i = 0; i < 4; ++i)
        stock_handles[i] = &fake_handles[i];
    stock_slots[0] = &fake_slots[0];
    stock_slots[1] = &fake_slots[1];
    owner = getpid();
    armed = 1;
}
static void install(void)
{
    errno = EDOM;
    assert(intercept_usleep(100000, IDLE_LR) == -1);
    assert(errno == EINTR && last_delay == 100000);
    assert(installed && !disabled && setter_calls == 2);
    assert(fake_slots[0] == main_frame && fake_slots[1] == sub_frame);
}
static void foreign(void *a, int32_t b, int32_t c, uint64_t d)
{
    (void)a; (void)b; (void)c; (void)d;
}
static void assert_no_forward(void)
{
    int before = sends;
    fake_slots[0]((void *)9, 7, 0, UINT64_C(0xfedcba9876543210));
    fake_slots[1]((void *)9, 7, 1, UINT64_C(0xfedcba9876543210));
    assert(sends == before);
    assert(fake_slots[0] == main_frame && fake_slots[1] == sub_frame);
}

static void *sending_thread(void *unused)
{
    (void)unused;
    main_frame((void *)9, 7, 0, UINT64_C(0xfedcba9876543210));
    return NULL;
}
static void *stopping_thread(void *unused)
{
    (void)unused;
    pthread_mutex_lock(&observations);
    stop_entered = 1;
    pthread_cond_broadcast(&observation_changed);
    pthread_mutex_unlock(&observations);
    assert(intercept_lock(&fake_mutex, STOP_LR) == 0);
    pthread_mutex_unlock(&fake_mutex);
    pthread_mutex_lock(&observations);
    stop_completed = 1;
    pthread_cond_broadcast(&observation_changed);
    pthread_mutex_unlock(&observations);
    return NULL;
}

int main(int argc, char **argv)
{
    const char *name;
    assert(argc == 2);
    name = argv[1];
    setup();
    if (!strcmp(name, "abi")) {
        install();
        fake_slots[0]((void *)9, 7, -123, UINT64_C(0xfedcba9876543210));
        assert(sends == 1 && last_channel == 0 && last_data == (void *)9);
        assert(last_length == 7 && last_timestamp == UINT64_C(0xfedcba9876543210));
        fake_slots[1]((void *)11, 13, 1, UINT64_C(0x12345678abcdef01));
        assert(sends == 2 && last_channel == 1 && last_data == (void *)11);
        assert(last_length == 13 && last_timestamp == UINT64_C(0x12345678abcdef01));
    } else if (!strcmp(name, "bad-buffer-length")) {
        install();
        fake_slots[0](NULL, 7, 0, 1);
        fake_slots[0]((void *)9, 0, 0, 1);
        fake_slots[1]((void *)9, -1, 1, 1);
        assert(sends == 0);
    } else if (!strcmp(name, "callsite")) {
        assert(intercept_usleep(100000, IDLE_LR + 4) == -1);
        assert(intercept_usleep(100001, IDLE_LR) == -1);
        assert(!installed && sleeps == 2 && last_delay == 100001);
    } else if (!strcmp(name, "unarmed")) {
        armed = 0;
        assert(intercept_usleep(100000, IDLE_LR) == -1);
        assert(!installed && !attempts && !locks && sleeps == 1);
    } else if (!strcmp(name, "fork-owner")) {
        owner = getpid() + 1;
        assert(intercept_usleep(100000, IDLE_LR) == -1);
        main_frame((void *)9, 7, 0, 1);
        assert(!installed && !locks && !sends && sleeps == 1);
    } else if (!strcmp(name, "not-initialized")) {
        fake_initialized = 0;
        intercept_usleep(100000, IDLE_LR);
        assert(!installed && !disabled);
    } else if (!strcmp(name, "missing-handles")) {
        unsigned i;
        for (i = 0; i < 4; ++i) {
            void *saved = fake_handles[i];
            fake_handles[i] = NULL;
            intercept_usleep(100000, IDLE_LR);
            assert(!installed && !disabled);
            fake_handles[i] = saved;
        }
        install();
    } else if (!strcmp(name, "busy-start")) {
        fake_busy = 1;
        intercept_usleep(100000, IDLE_LR);
        assert(!installed && !disabled);
        fake_busy = 0;
        install();
    } else if (!strcmp(name, "foreign-callback")) {
        fake_slots[1] = foreign;
        intercept_usleep(100000, IDLE_LR);
        assert(disabled && !installed && !setter_calls && fake_slots[1] == foreign);
    } else if (!strcmp(name, "deadline")) {
        fake_handles[3] = NULL;
        intercept_usleep(100000, IDLE_LR);
        fake_seconds = READY_SECONDS;
        intercept_usleep(100000, IDLE_LR);
        assert(disabled && !installed && sleeps == 2);
    } else if (!strcmp(name, "attempt-budget")) {
        int i;
        fake_handles[3] = NULL;
        for (i = 0; i <= READY_ATTEMPTS; ++i)
            intercept_usleep(100000, IDLE_LR);
        assert(disabled && !installed);
    } else if (!strcmp(name, "clock-failure")) {
        fake_clock_failure = 1;
        intercept_usleep(100000, IDLE_LR);
        assert(disabled && !installed);
    } else if (!strcmp(name, "join-teardown")) {
        void *result = NULL;
        install();
        assert(intercept_join((pthread_t)1, &result, JOIN_LR) == 23);
        assert(result == (void *)17 && joins == 1 && disabled);
        assert_no_forward();
        intercept_usleep(100000, IDLE_LR);
        assert(setter_calls == 2);
    } else if (!strcmp(name, "stop-teardown")) {
        install();
        assert(intercept_lock(&fake_mutex, STOP_LR) == 0);
        assert(disabled);
        pthread_mutex_unlock(&fake_mutex);
        assert_no_forward();
    } else if (!strcmp(name, "other-lifecycle-calls")) {
        pthread_mutex_t unrelated = PTHREAD_MUTEX_INITIALIZER;
        install();
        assert(intercept_join((pthread_t)1, NULL, JOIN_LR + 4) == 23);
        assert(intercept_lock(&unrelated, STOP_LR) == 0);
        pthread_mutex_unlock(&unrelated);
        assert(intercept_lock(&fake_mutex, STOP_LR + 4) == 0);
        pthread_mutex_unlock(&fake_mutex);
        assert(!disabled);
        fake_slots[0]((void *)9, 7, 0, 1);
        assert(sends == 1);
    } else if (!strcmp(name, "drain-inflight")) {
        pthread_t sending, stopping;
        install();
        block_send = 1;
        assert(pthread_create(&sending, NULL, sending_thread, NULL) == 0);
        pthread_mutex_lock(&observations);
        while (!send_entered)
            pthread_cond_wait(&observation_changed, &observations);
        pthread_mutex_unlock(&observations);
        assert(pthread_create(&stopping, NULL, stopping_thread, NULL) == 0);
        pthread_mutex_lock(&observations);
        while (!stop_entered)
            pthread_cond_wait(&observation_changed, &observations);
        pthread_mutex_unlock(&observations);
        usleep(20000);
        pthread_mutex_lock(&observations);
        assert(!stop_completed);
        release_send = 1;
        pthread_cond_broadcast(&observation_changed);
        pthread_mutex_unlock(&observations);
        assert(pthread_join(sending, NULL) == 0);
        assert(pthread_join(stopping, NULL) == 0);
        assert(stop_completed && disabled && sends == 1);
        assert_no_forward();
    } else if (!strcmp(name, "wrong-elf-env")) {
        armed = 0;
        setenv("LSCAMOFLASH_RTSP_PROFILE", "3007325.5", 1);
        setenv("LD_PRELOAD", "not-a-real-path", 1);
        initialize();
        assert(!armed && !getenv("LSCAMOFLASH_RTSP_PROFILE") && !getenv("LD_PRELOAD"));
        assert(!installed && !setter_calls);
    } else if (!strcmp(name, "identity")) {
        char path[] = "/tmp/camoflash-identity-XXXXXX";
        unsigned i;
        uint32_t corrupt = 0;
        int fd = mkstemp(path);
        assert(fd >= 0);
        unlink(path);
        assert(ftruncate(fd, 5318856) == 0);
        assert(pwrite(fd, exact_header, sizeof(exact_header), 0) == sizeof(exact_header));
        for (i = 0; i < sizeof(signatures) / sizeof(signatures[0]); ++i)
            assert(pwrite(fd, signatures[i].words, 16, signatures[i].address - 0x10000) == 16);
        assert(identity_fd(fd));
        assert(pwrite(fd, &corrupt, 4, signatures[0].address - 0x10000) == 4);
        assert(!identity_fd(fd));
        assert(pwrite(fd, signatures[0].words, 16, signatures[0].address - 0x10000) == 16);
        assert(pwrite(fd, &corrupt, 4, 0) == 4);
        assert(!identity_fd(fd));
        assert(pwrite(fd, exact_header, sizeof(exact_header), 0) == sizeof(exact_header));
        assert(ftruncate(fd, 5318855) == 0 && !identity_fd(fd));
        close(fd);
    } else {
        assert(!"unknown fixture");
    }
    puts("PASS");
    return 0;
}
