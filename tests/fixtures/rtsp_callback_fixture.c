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
static audio_cb fake_audio_slot;
static int sends, last_channel, last_length, sleeps, locks, joins, setter_calls;
static int audio_sends, audio_length, audio_setter_calls;
static void *audio_data;
static uint64_t audio_timestamp;
static int fail_setter_step, fail_after_publication;
static void *last_data;
static uint64_t last_timestamp;
static useconds_t last_delay;
static int fake_clock_failure, fake_busy;
static pthread_mutex_t observations = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t observation_changed = PTHREAD_COND_INITIALIZER;
static int block_send, send_entered, release_send, stop_entered, stop_completed;
static int contender_entered;
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
    if (setter_calls == fail_setter_step && !fail_after_publication)
        return -1;
    fake_slots[channel] = callback;
    return setter_calls == fail_setter_step ? -1 : 0;
}
static int mock_set_audio(int channel, audio_cb callback)
{
    int step;
    assert(channel == 0 && callback);
    ++audio_setter_calls;
    step = setter_calls + audio_setter_calls;
    if (step == fail_setter_step && !fail_after_publication)
        return -1;
    fake_audio_slot = callback;
    return step == fail_setter_step ? -1 : 0;
}
static void block_sender(void)
{
    if (block_send) {
        pthread_mutex_lock(&observations);
        send_entered = 1;
        pthread_cond_broadcast(&observation_changed);
        while (!release_send)
            pthread_cond_wait(&observation_changed, &observations);
        pthread_mutex_unlock(&observations);
    }
}
static void mock_send(int channel, void *data, int length, uint64_t timestamp)
{
    ++sends;
    last_channel = channel;
    last_data = data;
    last_length = length;
    last_timestamp = timestamp;
    block_sender();
}
static void mock_send_audio(void *data, int32_t length, uint64_t timestamp)
{
    /* The stock sender fans out to both sessions. The helper calls it once. */
    ++audio_sends;
    audio_data = data;
    audio_length = length;
    audio_timestamp = timestamp;
    block_sender();
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
    set_audio_callback = mock_set_audio;
    send_video = mock_send;
    send_audio = mock_send_audio;
    stock_mutex = &fake_mutex;
    stock_initialized = &fake_initialized;
    for (i = 0; i < 4; ++i)
        stock_handles[i] = &fake_handles[i];
    stock_slots[0] = &fake_slots[0];
    stock_slots[1] = &fake_slots[1];
    stock_audio_slot = &fake_audio_slot;
    owner = getpid();
    armed = 1;
}
static void install(void)
{
    errno = EDOM;
    assert(intercept_usleep(100000, IDLE_LR) == -1);
    assert(errno == EINTR && last_delay == 100000);
    assert(installed && !disabled && setter_calls == 2 && audio_setter_calls == 1);
    assert(fake_slots[0] == main_frame && fake_slots[1] == sub_frame);
    assert(fake_audio_slot == audio_frame);
}
static void foreign(void *a, int32_t b, int32_t c, uint64_t d)
{
    (void)a; (void)b; (void)c; (void)d;
}
static void foreign_audio(void *data, int32_t length, uint64_t timestamp)
{
    (void)data; (void)length; (void)timestamp;
}
static void assert_no_forward(void)
{
    int before = sends, before_audio = audio_sends;
    fake_slots[0]((void *)9, 7, 0, UINT64_C(0xfedcba9876543210));
    fake_slots[1]((void *)9, 7, 1, UINT64_C(0xfedcba9876543210));
    fake_audio_slot((void *)9, 7, UINT64_C(0xfedcba9876543210));
    assert(sends == before && audio_sends == before_audio);
    assert(fake_slots[0] == main_frame && fake_slots[1] == sub_frame);
    assert(fake_audio_slot == audio_frame);
}

static void *sending_thread(void *audio)
{
    if (audio)
        audio_frame((void *)9, 7, UINT64_C(0xfedcba9876543210));
    else
        main_frame((void *)9, 7, 0, UINT64_C(0xfedcba9876543210));
    return NULL;
}
static void *stopping_thread(void *join_stop)
{
    pthread_mutex_lock(&observations);
    stop_entered = 1;
    pthread_cond_broadcast(&observation_changed);
    pthread_mutex_unlock(&observations);
    if (join_stop) {
        assert(intercept_join((pthread_t)1, NULL, JOIN_LR) == 23);
    } else {
        assert(intercept_lock(&fake_mutex, STOP_LR) == 0);
        pthread_mutex_unlock(&fake_mutex);
    }
    pthread_mutex_lock(&observations);
    stop_completed = 1;
    pthread_cond_broadcast(&observation_changed);
    pthread_mutex_unlock(&observations);
    return NULL;
}

static void *contending_thread(void *audio)
{
    pthread_mutex_lock(&observations);
    contender_entered = 1;
    pthread_cond_broadcast(&observation_changed);
    pthread_mutex_unlock(&observations);
    return sending_thread(audio);
}
static void wait_for_flag(int *flag)
{
    pthread_mutex_lock(&observations);
    while (!*flag)
        pthread_cond_wait(&observation_changed, &observations);
    pthread_mutex_unlock(&observations);
}
static void release_sender(void)
{
    release_send = 1;
    pthread_cond_broadcast(&observation_changed);
}
static void check_failed_install(int step, int after_publication)
{
    video_cb saved_video[2];
    audio_cb saved_audio;
    int i;
    fail_setter_step = step;
    fail_after_publication = after_publication;
    intercept_usleep(100000, IDLE_LR);
    assert(disabled && !installed);
    assert(setter_calls + audio_setter_calls == step);
    assert(fake_slots[0] == ((step > 1 || after_publication) ? main_frame : NULL));
    assert(fake_slots[1] == ((step > 2 || (step == 2 && after_publication)) ? sub_frame : NULL));
    assert(fake_audio_slot == ((step == 3 && after_publication) ? audio_frame : NULL));
    for (i = 0; i < 2; ++i) {
        saved_video[i] = fake_slots[i];
        if (fake_slots[i])
            fake_slots[i]((void *)9, 7, 0, 1);
    }
    saved_audio = fake_audio_slot;
    if (fake_audio_slot)
        fake_audio_slot((void *)9, 7, UINT64_C(0xfedcba9876543210));
    assert(!sends && !audio_sends);
    intercept_usleep(100000, IDLE_LR);
    assert(setter_calls + audio_setter_calls == step); /* No retry or clearing. */
    assert(fake_slots[0] == saved_video[0] && fake_slots[1] == saved_video[1]);
    assert(fake_audio_slot == saved_audio);
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
    } else if (!strcmp(name, "audio-abi")) {
        unsigned char borrowed[] = {0xa1, 0x10, 0x20, 0x30, 0x40, 0x50, 0xb2};
        unsigned char original[sizeof(borrowed)];
        memcpy(original, borrowed, sizeof(borrowed));
        install();
        fake_audio_slot(borrowed + 1, 5, UINT64_C(0xfedcba9876543210));
        assert(audio_sends == 1 && sends == 0 && audio_data == borrowed + 1);
        assert(audio_length == 5 && audio_timestamp == UINT64_C(0xfedcba9876543210));
        fake_audio_slot(borrowed + 2, 3, UINT64_C(0x12345678abcdef01));
        assert(audio_sends == 2 && audio_data == borrowed + 2 && audio_length == 3);
        assert(audio_timestamp == UINT64_C(0x12345678abcdef01));
        fake_audio_slot(borrowed + 1, 1, 0);
        assert(audio_sends == 3 && audio_timestamp == 0);
        assert(!memcmp(original, borrowed, sizeof(borrowed)));
    } else if (!strcmp(name, "audio-bad-buffer-length")) {
        int before;
        install();
        before = locks;
        fake_audio_slot(NULL, 7, 1);
        fake_audio_slot((void *)9, 0, 1);
        fake_audio_slot((void *)9, -1, 1);
        fake_audio_slot((void *)9, INT32_MIN, UINT64_MAX);
        assert(!audio_sends && !sends && locks == before);
    } else if (!strcmp(name, "audio-owner-guards")) {
        int before;
        install();
        before = locks;
        owner = getpid() + 1;
        fake_audio_slot((void *)9, 7, 1);
        owner = getpid();
        armed = 0;
        fake_audio_slot((void *)9, 7, 1);
        assert(!audio_sends && locks == before);
    } else if (!strcmp(name, "audio-before-install")) {
        audio_frame((void *)9, 7, 1);
        assert(!audio_sends && !sends && !installed);
    } else if (!strcmp(name, "foreign-audio-callback")) {
        fake_audio_slot = foreign_audio;
        intercept_usleep(100000, IDLE_LR);
        assert(disabled && !installed && !setter_calls && !audio_setter_calls);
        assert(fake_audio_slot == foreign_audio && !fake_slots[0] && !fake_slots[1]);
    } else if (!strcmp(name, "install-failure-video0")) {
        check_failed_install(1, 0);
    } else if (!strcmp(name, "install-failure-video1")) {
        check_failed_install(2, 0);
    } else if (!strcmp(name, "install-failure-audio")) {
        check_failed_install(3, 0);
    } else if (!strcmp(name, "install-failure-published-video0")) {
        check_failed_install(1, 1);
    } else if (!strcmp(name, "install-failure-published-video1")) {
        check_failed_install(2, 1);
    } else if (!strcmp(name, "install-failure-published-audio")) {
        check_failed_install(3, 1);
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
        audio_frame((void *)9, 7, 1);
        assert(!installed && !locks && !sends && !audio_sends && sleeps == 1);
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
        assert(setter_calls == 2 && audio_setter_calls == 1);
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
    } else if (!strcmp(name, "drain-inflight") ||
               !strcmp(name, "audio-drain-inflight") || !strcmp(name, "audio-drain-join")) {
        pthread_t sending, stopping;
        int audio = strcmp(name, "drain-inflight") != 0;
        int join_stop = !strcmp(name, "audio-drain-join");
        install();
        block_send = 1;
        assert(pthread_create(&sending, NULL, sending_thread, (void *)(uintptr_t)audio) == 0);
        pthread_mutex_lock(&observations);
        while (!send_entered)
            pthread_cond_wait(&observation_changed, &observations);
        pthread_mutex_unlock(&observations);
        assert(pthread_create(&stopping, NULL, stopping_thread, (void *)(uintptr_t)join_stop) == 0);
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
        assert(stop_completed && disabled);
        assert(sends == (audio ? 0 : 1) && audio_sends == (audio ? 1 : 0));
        assert_no_forward();
    } else if (!strcmp(name, "audio-video-serialization") ||
               !strcmp(name, "video-audio-serialization")) {
        pthread_t first, second;
        int first_audio = !strcmp(name, "audio-video-serialization");
        install();
        block_send = 1;
        assert(pthread_create(&first, NULL, sending_thread, (void *)(uintptr_t)first_audio) == 0);
        wait_for_flag(&send_entered);
        assert(pthread_create(&second, NULL, contending_thread, (void *)(uintptr_t)!first_audio) == 0);
        wait_for_flag(&contender_entered);
        usleep(20000);
        pthread_mutex_lock(&observations);
        assert(sends == (first_audio ? 0 : 1));
        assert(audio_sends == (first_audio ? 1 : 0));
        release_sender();
        pthread_mutex_unlock(&observations);
        assert(pthread_join(first, NULL) == 0 && pthread_join(second, NULL) == 0);
        assert(sends == 1 && audio_sends == 1 && !disabled);
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
