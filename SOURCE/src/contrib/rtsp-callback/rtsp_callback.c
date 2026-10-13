/* Experimental callbacks for the exact 3007325.5 stock executable only.
 * The wrapper separately verifies its full SHA256. These ELF/opcode/export
 * guards prevent fixed-address access from an accidentally preloaded program.
 * No camera settings, frame bytes, sockets or flash devices are written here.
 */
#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

#define IDLE_LR ((uintptr_t)0xced24)
#define STOP_LR ((uintptr_t)0xbd4fc)
#define JOIN_LR ((uintptr_t)0xbd9b0)
#define STOCK_MUTEX ((uintptr_t)0x5378b0)
#define READY_SECONDS 10
#define READY_ATTEMPTS 101

typedef void (*video_cb)(void *, int32_t, int32_t, uint64_t);
typedef void (*audio_cb)(void *, int32_t, uint64_t);
typedef int (*set_cb_fn)(int, video_cb);
typedef int (*set_audio_fn)(int, audio_cb);
typedef void (*send_fn)(int, void *, int, uint64_t);

static int (*next_usleep)(useconds_t);
static int (*next_lock)(pthread_mutex_t *);
static int (*next_unlock)(pthread_mutex_t *);
static int (*next_trylock)(pthread_mutex_t *);
static int (*next_join)(pthread_t, void **);
static int (*get_time)(clockid_t, struct timespec *) = clock_gettime;
static set_cb_fn set_callback;
static set_audio_fn set_audio_callback;
static send_fn send_video;
static audio_cb send_audio;
static pthread_mutex_t lifecycle = PTHREAD_MUTEX_INITIALIZER;
static pthread_mutex_t *stock_mutex;
static volatile uint32_t *stock_initialized;
static void *volatile *stock_handles[4];
static video_cb volatile *stock_slots[2];
static audio_cb volatile *stock_audio_slot;
static pid_t owner;
static int armed, installed, disabled, attempts, clock_started;
static struct timespec started;

static pthread_once_t real_once = PTHREAD_ONCE_INIT;

static void resolve_real_functions(void)
{
    next_usleep = dlsym(RTLD_NEXT, "usleep");
    next_lock = dlsym(RTLD_NEXT, "pthread_mutex_lock");
    next_unlock = dlsym(RTLD_NEXT, "pthread_mutex_unlock");
    next_trylock = dlsym(RTLD_NEXT, "pthread_mutex_trylock");
    next_join = dlsym(RTLD_NEXT, "pthread_join");
}

static void ensure_real_functions(void)
{
    /* A DT_NEEDED library may call an interposer from its constructor before
     * ours runs. Resolve once at first use, with publication synchronized for
     * concurrent callers. Stock dlsym uses protected internal mutex aliases. */
    (void)pthread_once(&real_once, resolve_real_functions);
}

static void main_frame(void *, int32_t, int32_t, uint64_t);
static void sub_frame(void *, int32_t, int32_t, uint64_t);
static void audio_frame(void *, int32_t, uint64_t);

static void phase(const char *message)
{
    /* A few bounded phase lines, never frame contents or environment values. */
    int saved = errno;
    ssize_t ignored = write(STDERR_FILENO, message, strlen(message));
    (void)ignored;
    errno = saved;
}

static int qualified(void)
{
    /* A fork child must not touch a mutex inherited from other threads. */
    return armed && owner == getpid();
}

static void disable_locked(const char *reason)
{
    if (!disabled) {
        disabled = 1;
        phase(reason);
    }
    /* NEVER clear published slots: the encoder tests then reloads the pointer
     * before BLX. Clearing it can race into a NULL call. Mapped callbacks stay
     * callable and simply stop forwarding until this process terminates. */
}

static void disable_forwarding(void)
{
    if (!qualified())
        return;
    next_lock(&lifecycle);
    disable_locked("camoflash-rtsp: forwarding-disabled\n");
    next_unlock(&lifecycle);
}

static int handles_ready(void)
{
    unsigned i;
    if (!*stock_initialized)
        return 0;
    for (i = 0; i < 4; ++i)
        if (!*stock_handles[i])
            return 0;
    return 1;
}

static void try_install(void)
{
    struct timespec now;
    int elapsed;
    next_lock(&lifecycle);
    if (installed || disabled)
        goto done;
    if (get_time(CLOCK_MONOTONIC, &now) != 0) {
        disable_locked("camoflash-rtsp: readiness-clock-failed\n");
        goto done;
    }
    if (!clock_started) {
        started = now;
        clock_started = 1;
    }
    elapsed = now.tv_sec - started.tv_sec >= READY_SECONDS;
    if (elapsed || ++attempts > READY_ATTEMPTS) {
        disable_locked("camoflash-rtsp: readiness-timeout\n");
        goto done;
    }
    /* The async start worker holds this mutex throughout both session setups.
     * A trylock keeps each natural 100ms idle-loop probe nonblocking. */
    if (!*stock_initialized || next_trylock(stock_mutex) != 0)
        goto done;
    if (handles_ready()) {
        /* The audio producer holds its codec mutex while calling us. This is
         * the only setter call: all slots must be NULL before publication, so
         * no producer can already be waiting on lifecycle through our audio
         * callback. Never clear/reinstall it under lifecycle after publishing;
         * that would invert the codec/lifecycle lock order. */
        if (*stock_slots[0] || *stock_slots[1] || *stock_audio_slot) {
            disable_locked("camoflash-rtsp: callback-conflict\n");
        } else if (set_callback(0, main_frame) != 0 ||
                   set_callback(1, sub_frame) != 0 ||
                   set_audio_callback(0, audio_frame) != 0) {
            disable_locked("camoflash-rtsp: callback-install-failed\n");
        } else {
            installed = 1;
            phase("camoflash-rtsp: callbacks-installed\n");
            phase("camoflash-rtsp: audio-callback-installed\n");
        }
    }
    next_unlock(stock_mutex);
done:
    next_unlock(&lifecycle);
}

static void forward_frame(int channel, void *data, int32_t length,
                          uint64_t timestamp_ms)
{
    if (!qualified() || !data || length <= 0)
        return;
    /* The framebuffer is borrowed from the encoder and consumed synchronously.
     * This process-lifetime mutex drains in-flight sends before either stock
     * stop/free path proceeds. The RTSP call tree does not take this mutex. */
    next_lock(&lifecycle);
    if (installed && !disabled)
        send_video(channel, data, length, timestamp_ms);
    next_unlock(&lifecycle);
}

static void main_frame(void *data, int32_t length, int32_t frame_type,
                       uint64_t timestamp_ms)
{
    (void)frame_type;
    forward_frame(0, data, length, timestamp_ms);
}

static void sub_frame(void *data, int32_t length, int32_t frame_type,
                      uint64_t timestamp_ms)
{
    (void)frame_type;
    forward_frame(1, data, length, timestamp_ms);
}

static void audio_frame(void *data, int32_t length, uint64_t timestamp_ms)
{
    if (!qualified() || !data || length <= 0)
        return;
    /* The stock encoder owns this G.711 A-law buffer until we return. Its
     * sender fans out to both sessions and converts milliseconds internally.
     * Serialize with video/event handling and drain on the same stop gate. */
    next_lock(&lifecycle);
    if (installed && !disabled)
        send_audio(data, length, timestamp_ms);
    next_unlock(&lifecycle);
}

static int intercept_usleep(useconds_t usec, uintptr_t caller)
{
    int saved = errno;
    ensure_real_functions();
    if (qualified() && caller == IDLE_LR && usec == 100000)
        try_install();
    errno = saved;
    if (!next_usleep) {
        errno = ENOSYS;
        return -1;
    }
    return next_usleep(usec);
}

static int intercept_lock(pthread_mutex_t *mutex, uintptr_t caller)
{
    int saved = errno;
    ensure_real_functions();
    if (qualified() && caller == STOP_LR && mutex == stock_mutex)
        disable_forwarding();
    errno = saved;
    return next_lock ? next_lock(mutex) : EINVAL;
}

static int intercept_join(pthread_t thread, void **result, uintptr_t caller)
{
    int saved = errno;
    ensure_real_functions();
    if (qualified() && caller == JOIN_LR)
        disable_forwarding();
    errno = saved;
    return next_join ? next_join(thread, result) : EINVAL;
}

int usleep(useconds_t usec)
{
    return intercept_usleep(usec, (uintptr_t)__builtin_return_address(0));
}

int pthread_mutex_lock(pthread_mutex_t *mutex)
{
    return intercept_lock(mutex, (uintptr_t)__builtin_return_address(0));
}

int pthread_join(pthread_t thread, void **result)
{
    return intercept_join(thread, result, (uintptr_t)__builtin_return_address(0));
}

static const unsigned char exact_header[52] = {
    0x7f,0x45,0x4c,0x46,0x01,0x01,0x01,0,0,0,0,0,0,0,0,0,
    0x02,0,0x28,0,0x01,0,0,0,0xa0,0x43,0x08,0,0x34,0,0,0,
    0x40,0x24,0x51,0,0,0x02,0,0x05,0x34,0,0x20,0,0x08,0,
    0x28,0,0x1d,0,0x1c,0
};

static const struct signature {
    uint32_t address;
    uint32_t words[4];
} signatures[] = {
    {0xced1c, {0xe59f00ec,0xebfecc7f,0xe59f30e8,0xe08f3003}},
    {0xbd9ac, {0xebff127f,0xebfffebf,0xe59f3074,0xe08f3003}},
    {0xbd4ec, {0xe59f3110,0xe08f3003,0xe2830018,0xebff11d8}},
    {0xc376c, {0xe52db004,0xe28db000,0xe24dd00c,0xe50b0008}},
    {0xbcf08, {0xe92d4810,0xe28db008,0xe24dd01c,0xe50b0010}},
    {0xc0a44, {0xe51b301c,0xe593303c,0xe3530000,0x0a000011}},
    {0xc21dc, {0xe51b3028,0xe593303c,0xe3530000,0x0a000020}},
    {0xa915c, {0xe92d4800,0xe28db004,0xe24dd010,0xe50b0010}},
    {0xa91c8, {0xe51b300c,0xe51b2014,0xe5832024,0xe51b300c}},
    {0xa5d84, {0xe5933024,0xe3530000,0x0a00000a,0xe51b3038}},
    {0xa5da4, {0xebffbd69,0xe1a02000,0xe1a03001,0xe1a00005}},
    {0xbcfd0, {0xe92d4800,0xe28db004,0xe24dd018,0xe50b0008}}
};

static int identity_fd(int fd)
{
    unsigned char header[52];
    uint32_t words[4];
    struct stat st;
    unsigned i;
    if (fstat(fd, &st) || !S_ISREG(st.st_mode) || st.st_size != 5318856 ||
        pread(fd, header, sizeof(header), 0) != (ssize_t)sizeof(header) ||
        memcmp(header, exact_header, sizeof(header)))
        return 0;
    for (i = 0; i < sizeof(signatures) / sizeof(signatures[0]); ++i) {
        if (pread(fd, words, sizeof(words), signatures[i].address - 0x10000) !=
            (ssize_t)sizeof(words) ||
            memcmp(words, signatures[i].words, sizeof(words)))
            return 0;
    }
    return 1;
}

#ifndef CAMOFLASH_RTSP_TEST
__attribute__((constructor))
#endif
static void initialize(void)
{
    const char *profile = getenv("LSCAMOFLASH_RTSP_PROFILE");
    int requested = profile && !strcmp(profile, "3007325.5");
    int fd, identity;
    ensure_real_functions();
    /* LD_PRELOAD is scoped to this exec. Removing it does not unload this DSO,
     * and prevents stock fork/exec helpers from loading the hook again. */
    if (profile) {
        unsetenv("LSCAMOFLASH_RTSP_PROFILE");
        unsetenv("LD_PRELOAD");
    }
    if (!requested || !next_usleep || !next_lock || !next_unlock ||
        !next_trylock || !next_join)
        return;
    fd = open("/proc/self/exe", O_RDONLY | O_CLOEXEC);
    if (fd < 0)
        return;
    identity = identity_fd(fd);
    close(fd);
    if (!identity || sizeof(void *) != 4 || sizeof(pthread_mutex_t) != 24)
        return;
    set_callback = dlsym(RTLD_DEFAULT, "ht_video_codec_set_get_venc_cb");
    set_audio_callback = dlsym(RTLD_DEFAULT, "ht_audio_codec_set_get_aenc_cb");
    send_video = dlsym(RTLD_DEFAULT, "ht_rtsp_send_video_frame");
    send_audio = dlsym(RTLD_DEFAULT, "ht_rtsp_send_audio_frame");
    if ((uintptr_t)set_callback != 0xc376c ||
        (uintptr_t)set_audio_callback != 0xa915c ||
        (uintptr_t)send_video != 0xbcf08 ||
        (uintptr_t)send_audio != 0xbcfd0 ||
        (uintptr_t)dlsym(RTLD_DEFAULT, "ht_rtsp_init") != 0xbd770 ||
        (uintptr_t)dlsym(RTLD_DEFAULT, "ht_rtsp_deinit") != 0xbd960)
        return;
    stock_mutex = (pthread_mutex_t *)STOCK_MUTEX;
    stock_initialized = (volatile uint32_t *)0x5378cc;
    stock_handles[0] = (void *volatile *)0x53789c;
    stock_handles[1] = (void *volatile *)0x5378a0;
    stock_handles[2] = (void *volatile *)0x5378a4;
    stock_handles[3] = (void *volatile *)0x5378a8;
    stock_slots[0] = (video_cb volatile *)0x537964;
    stock_slots[1] = (video_cb volatile *)0x5379a4;
    stock_audio_slot = (audio_cb volatile *)0x534954;
    owner = getpid();
    armed = 1;
    phase("camoflash-rtsp: exact-profile-armed\n");
}
