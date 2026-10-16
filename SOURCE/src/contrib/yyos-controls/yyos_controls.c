/* Native controls for the exact LSC 3225722 / SZ F26312 YYOS 14.1.5 profile.
 * Owner keys enter through stdin only. No arbitrary endpoint/DP/JSON interface.
 * Crypto/session code uses the independently tested minimal LTC build.
 * PTZ safety is a logical stop deadline, not a physical hard-real-time claim:
 * native SDK queues, kernel failure and concurrent app commands remain external.
 */
#define _GNU_SOURCE
#include <arpa/inet.h>
#include <errno.h>
#include <dirent.h>
#include <fcntl.h>
#include <poll.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/utsname.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>
#include "tomcrypt.h"

#define CAP 8192
#define TOKEN_CAP 512
#define JOG_MS 200
#define LAUNCH_MS 50
#define STOP_BUDGET_MS 1000
#define STOP_ATTEMPTS 3
static int aes_index, sha_index;
#ifndef YYOS_TEST_FIXTURE
static pid_t verified_stock_pid;
#endif
struct session { int fd; unsigned char key[16]; uint32_t sequence; };
struct properties { int indicator, osd, tracking; };
#ifdef YYOS_TEST_FIXTURE
static int fixture_fail_clock;
#endif

/* ----- Profile and clock guards; no flash/configuration writes. ----- */
static int64_t monotonic_ms(void)
{
#ifdef YYOS_TEST_FIXTURE
    if (fixture_fail_clock) return -1;
#endif
    struct timespec t;
    if (clock_gettime(CLOCK_MONOTONIC, &t) || t.tv_sec < 0
            || t.tv_nsec < 0 || t.tv_nsec >= 1000000000)
        return -1;
    return (int64_t)t.tv_sec * 1000 + t.tv_nsec / 1000000;
}
static int sleep_ms(unsigned milliseconds)
{
    struct timespec t = {milliseconds / 1000,
                         (long)(milliseconds % 1000) * 1000000};
    while (nanosleep(&t, &t))
        if (errno != EINTR) return -1;
    return 0;
}
static int clock_ready(void)
{
    int64_t before = monotonic_ms();
    if (before < 0 || sleep_ms(20)) return -1;
    int64_t after = monotonic_ms();
    return after > before && after - before <= 1000 ? 0 : -1;
}
#ifndef YYOS_TEST_FIXTURE
static int exact_cpu(void)
{
    struct utsname name;
    char buffer[4096] = {0};
    int model = 0, architecture = 0, hardware = 0, result = -1;
    if (getuid() != 0 || geteuid() != 0 || uname(&name)
            || strcmp(name.machine, "armv5tejl")) return -1;
    int fd = open("/proc/cpuinfo", O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
    if (fd < 0) return -1;
    ssize_t bytes = read(fd, buffer, sizeof(buffer) - 1); close(fd);
    if (bytes <= 0 || bytes >= (ssize_t)sizeof(buffer) - 1) goto done;
    char *save, *line = strtok_r(buffer, "\n", &save);
    while (line) {
        char *colon = strchr(line, ':');
        if (colon) {
            *colon++ = 0;
            char *end = line + strlen(line);
            while (end > line && (end[-1] == ' ' || end[-1] == '\t')) *--end = 0;
            while (*colon == ' ' || *colon == '\t') ++colon;
            end = colon + strlen(colon);
            while (end > colon && (end[-1] == ' ' || end[-1] == '\t')) *--end = 0;
            if (!strcmp(line, "model name")) {
                if (strcmp(colon, "ARM926EJ-S rev 5 (v5l)")) goto done;
                ++model;
            } else if (!strcmp(line, "CPU architecture")) {
                if (strcmp(colon, "5TEJ")) goto done;
                ++architecture;
            } else if (!strcmp(line, "Hardware")) {
                if (strcmp(colon, "AK3918AV130")) goto done;
                ++hardware;
            }
        }
        line = strtok_r(NULL, "\n", &save);
    }
    result = model == 1 && architecture == 1 && hardware == 1 ? 0 : -1;
done:
    zeromem(buffer, sizeof(buffer));
    return result;
}
static int running_stock_matches(const struct stat *verified)
{
    DIR *proc = opendir("/proc");
    if (!proc) return -1;
    unsigned matches = 0, entries = 0; pid_t found = 0;
    struct dirent *entry;
    while ((entry = readdir(proc)) != NULL) {
        if (++entries > 65536) { matches = 0; break; }
        char *end; long pid = strtol(entry->d_name, &end, 10);
        if (*end || pid <= 0 || pid > 2147483647L) continue;
        char path[64];
        int n = snprintf(path, sizeof(path), "/proc/%ld/exe", pid);
        if (n < 0 || n >= (int)sizeof(path)) continue;
        /* /proc/PID/exe is a kernel magic link; following it is intentional. */
        int fd = open(path, O_RDONLY | O_CLOEXEC);
        if (fd < 0) continue;
        struct stat current;
        int same = !fstat(fd, &current) && S_ISREG(current.st_mode)
                   && current.st_dev == verified->st_dev
                   && current.st_ino == verified->st_ino
                   && current.st_size == verified->st_size;
        close(fd);
        if (same) { ++matches; found = (pid_t)pid; }
    }
    closedir(proc);
    if (matches != 1 || (verified_stock_pid && found != verified_stock_pid))
        return -1;
    verified_stock_pid = found;
    return 0;
}
#endif
static int profile_matches(void)
{
#ifdef YYOS_TEST_FIXTURE
    /* Fixture builds accept only the public synthetic key below. Never ship. */
    return 0;
#else
    static const unsigned char expected[32] = {
        0xd7,0x6d,0x63,0x2f,0x41,0x45,0x3f,0x53,
        0xd9,0xd1,0x17,0x58,0x2f,0xc4,0x70,0x73,
        0x93,0x4f,0x5e,0x6e,0xc9,0xa9,0xb7,0xa0,
        0xeb,0xb1,0xdd,0x38,0x24,0xf6,0xcb,0xa7};
    unsigned char buffer[4096], digest[32];
    hash_state state;
    struct stat st;
    int result = -1;
    if (exact_cpu()) return -1;
    int fd = open("/appfs/bin/yy_cam", O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
    if (fd < 0) return -1;
    if (fstat(fd, &st) || !S_ISREG(st.st_mode) || st.st_size < 1
            || st.st_size > 32 * 1024 * 1024) goto done;
    if (sha256_init(&state) != CRYPT_OK) goto done;
    for (;;) {
        ssize_t n = read(fd, buffer, sizeof(buffer));
        if (n < 0 && errno == EINTR) continue;
        if (n < 0) goto done;
        if (!n) break;
        if (sha256_process(&state, buffer, (unsigned long)n) != CRYPT_OK)
            goto done;
    }
    if (sha256_done(&state, digest) == CRYPT_OK
            && !memcmp(digest, expected, sizeof(expected))
            && !running_stock_matches(&st)) result = 0;
done:
    close(fd);
    zeromem(buffer, sizeof(buffer));
    zeromem(digest, sizeof(digest));
    zeromem(&state, sizeof(state));
    return result;
#endif
}
static int read_key(unsigned char key[16])
{
    size_t complete = 0;
    while (complete < 16) {
        ssize_t n = read(STDIN_FILENO, key + complete, 16 - complete);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) return -1;
        complete += (size_t)n;
    }
    for (unsigned i = 0; i < 16; ++i)
        if (key[i] < 33 || key[i] > 126) return -1;
#ifdef YYOS_TEST_FIXTURE
    #ifndef YYOS_FIXTURE_KEY
#error "Tests must explicitly supply their synthetic fixture key"
#endif
    if (memcmp(key, YYOS_FIXTURE_KEY, 16)) return -1;
#endif
    return 0;
}

/* ----- Authenticated Tuya 3.5 framing and independent sessions. ----- */
static void put32(unsigned char *p, uint32_t n)
{
    p[0] = n >> 24; p[1] = n >> 16; p[2] = n >> 8; p[3] = n;
}
static uint32_t get32(const unsigned char *p)
{
    return (uint32_t)p[0] << 24 | (uint32_t)p[1] << 16
           | (uint32_t)p[2] << 8 | p[3];
}
static int equal_tag(const unsigned char *a, const unsigned char *b, size_t n)
{
    volatile unsigned char different = 0;
    while (n--) different |= *a++ ^ *b++;
    return different == 0;
}
static int random_bytes(unsigned char *p, size_t n)
{
    int fd = open("/dev/urandom", O_RDONLY | O_CLOEXEC);
    if (fd < 0) return -1;
    while (n) {
        ssize_t got = read(fd, p, n);
        if (got < 0 && errno == EINTR) continue;
        if (got <= 0) { close(fd); return -1; }
        p += got; n -= (size_t)got;
    }
    close(fd);
    return 0;
}
static int hmac256(const unsigned char key[16], const unsigned char *p,
                   size_t n, unsigned char out[32])
{
    unsigned long bytes = 32;
    return hmac_memory(sha_index, key, 16, p, n, out, &bytes) == CRYPT_OK
           && bytes == 32 ? 0 : -1;
}
static int gcm(const unsigned char key[16], const unsigned char iv[12],
               const unsigned char *aad, size_t aad_bytes,
               unsigned char *plain, size_t bytes, unsigned char *cipher,
               unsigned char tag[16], int direction)
{
    unsigned long tag_bytes = 16;
    return gcm_memory(aes_index, key, 16, iv, 12, aad, aad_bytes, plain,
                      bytes, cipher, tag, &tag_bytes, direction) == CRYPT_OK
           && tag_bytes == 16 ? 0 : -1;
}
static int pack_frame(unsigned char out[CAP], size_t *size,
                      const unsigned char key[16], uint32_t sequence,
                      uint32_t command, const unsigned char *body, size_t n)
{
    unsigned char iv[12], tag[16];
    if (n > CAP - 50 || random_bytes(iv, sizeof(iv))) return -1;
    put32(out, 0x6699); out[4] = out[5] = 0;
    put32(out + 6, sequence); put32(out + 10, command);
    put32(out + 14, (uint32_t)n + 28);
    memcpy(out + 18, iv, 12);
    if (gcm(key, iv, out + 4, 14, (unsigned char *)body, n,
            out + 30, tag, GCM_ENCRYPT)) return -1;
    memcpy(out + 30 + n, tag, 16); put32(out + 46 + n, 0x9966);
    *size = n + 50;
    zeromem(tag, sizeof(tag));
    return 0;
}
static int unpack_frame(const unsigned char *frame, size_t n,
                        const unsigned char key[16], unsigned char plain[CAP],
                        size_t *bytes, uint32_t *command)
{
    unsigned char tag[16];
    if (n < 50 || get32(frame) != 0x6699 || frame[4] || frame[5]
            || get32(frame + 14) != n - 22
            || get32(frame + n - 4) != 0x9966) return -1;
    size_t payload = n - 50;
    if (payload > CAP - 1) return -1;
    int ok = !gcm(key, frame + 18, frame + 4, 14, plain, payload,
                  (unsigned char *)frame + 30, tag, GCM_DECRYPT)
             && equal_tag(tag, frame + n - 20, 16);
    zeromem(tag, sizeof(tag));
    if (!ok) { zeromem(plain, payload); return -1; }
    *bytes = payload; *command = get32(frame + 10); plain[payload] = 0;
    return 0;
}
/* Every wait and the actual send after poll recheck the same monotonic limit. */
static int transfer(int fd, unsigned char *p, size_t n, int writing,
                     int64_t deadline)
{
    while (n) {
        int64_t now = monotonic_ms();
        if (now < 0 || deadline <= now || deadline - now > 15000) return -1;
        struct pollfd pollfd = {fd, writing ? POLLOUT : POLLIN, 0};
        int ready = poll(&pollfd, 1, (int)(deadline - now));
        if (ready < 0 && errno == EINTR) continue;
        if (ready <= 0 || (pollfd.revents & (POLLERR | POLLNVAL))) return -1;
        now = monotonic_ms();
        if (now < 0 || deadline <= now) return -1;
        ssize_t done = writing ? send(fd, p, n, MSG_NOSIGNAL)
                               : recv(fd, p, n, 0);
        if (done < 0 && (errno == EINTR || errno == EAGAIN
                        || errno == EWOULDBLOCK)) continue;
        if (done <= 0) return -1;
        p += done; n -= (size_t)done;
    }
    return 0;
}
static int send_frame(struct session *s, uint32_t command,
                       const unsigned char *body, size_t bytes, int64_t deadline)
{
    unsigned char frame[CAP]; size_t n;
    int result = -1;
    if (!pack_frame(frame, &n, s->key, s->sequence++, command, body, bytes))
        result = transfer(s->fd, frame, n, 1, deadline);
    zeromem(frame, sizeof(frame));
    return result;
}
static int receive_frame(struct session *s, unsigned char plain[CAP],
                          size_t *bytes, uint32_t *command, int64_t deadline)
{
    unsigned char frame[CAP]; int result = -1;
    if (transfer(s->fd, frame, 18, 0, deadline)) goto done;
    uint32_t n = get32(frame + 14);
    if (n < 28 || n > CAP - 22
            || transfer(s->fd, frame + 18, n + 4, 0, deadline)) goto done;
    result = unpack_frame(frame, n + 22, s->key, plain, bytes, command);
done:
    zeromem(frame, sizeof(frame));
    return result;
}
static void close_session(struct session *s)
{
    if (s->fd >= 0) close(s->fd);
    s->fd = -1; zeromem(s->key, sizeof(s->key)); s->sequence = 0;
}
static int connect_local(int64_t deadline)
{
    int fd = socket(AF_INET, SOCK_STREAM | SOCK_CLOEXEC, 0);
    if (fd < 0) return -1;
    if (fcntl(fd, F_SETFL, O_NONBLOCK)) { close(fd); return -1; }
    struct sockaddr_in address = {0};
    address.sin_family = AF_INET; address.sin_port = htons(6668);
    address.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    if (connect(fd, (struct sockaddr *)&address, sizeof(address))
            && errno != EINPROGRESS) { close(fd); return -1; }
    int64_t now = monotonic_ms();
    if (now < 0 || deadline <= now || deadline - now > 15000) {
        close(fd); return -1;
    }
    struct pollfd p = {fd, POLLOUT, 0};
    int error = 0; socklen_t length = sizeof(error);
    if (poll(&p, 1, (int)(deadline - now)) <= 0
            || getsockopt(fd, SOL_SOCKET, SO_ERROR, &error, &length) || error) {
        close(fd); return -1;
    }
    return fd;
}
static int open_session(struct session *s, const unsigned char local_key[16],
                         int64_t deadline)
{
    unsigned char local[16], remote[16], response[CAP], check[32],
                  finish[32], mixed[16], tag[16];
    size_t bytes; uint32_t command; int result = -1;
    s->fd = connect_local(deadline); s->sequence = 1;
    memcpy(s->key, local_key, 16);
    if (s->fd < 0 || random_bytes(local, 16)
            || send_frame(s, 3, local, 16, deadline)) goto done;
    if (receive_frame(s, response, &bytes, &command, deadline)
            || command != 4 || bytes != 52 || get32(response)) goto done;
    memcpy(remote, response + 4, 16);
    if (hmac256(local_key, local, 16, check)
            || !equal_tag(check, response + 20, 32)
            || hmac256(local_key, remote, 16, finish)
            || send_frame(s, 5, finish, 32, deadline)) goto done;
    for (unsigned i = 0; i < 16; ++i) mixed[i] = local[i] ^ remote[i];
    if (gcm(local_key, local, NULL, 0, mixed, 16, s->key, tag, GCM_ENCRYPT))
        goto done;
    result = 0;
done:
    zeromem(local, sizeof(local)); zeromem(remote, sizeof(remote));
    zeromem(response, sizeof(response)); zeromem(check, sizeof(check));
    zeromem(finish, sizeof(finish)); zeromem(mixed, sizeof(mixed));
    zeromem(tag, sizeof(tag));
    if (result) close_session(s);
    return result;
}

/* ----- Small bounded JSON reader: never prints unknown DPs or string values. */
enum kind { J_OBJECT, J_ARRAY, J_STRING, J_NUMBER, J_TRUE, J_FALSE, J_NULL };
struct token { enum kind kind; size_t start, end; unsigned next; };
struct json { const unsigned char *text; size_t size, position;
              struct token tokens[TOKEN_CAP]; unsigned count; };
static void whitespace(struct json *j)
{
    while (j->position < j->size && (j->text[j->position] == ' '
            || j->text[j->position] == '\n' || j->text[j->position] == '\r'
            || j->text[j->position] == '\t')) ++j->position;
}
static int parse_string(struct json *j)
{
    if (j->position >= j->size || j->text[j->position++] != '"') return -1;
    while (j->position < j->size) {
        unsigned char c = j->text[j->position++];
        if (c == '"') return 0;
        if (c < 32) return -1;
        if (c != '\\') continue;
        if (j->position >= j->size) return -1;
        c = j->text[j->position++];
        if (c && strchr("\"\\/bfnrt", c)) continue;
        if (c != 'u' || j->size - j->position < 4) return -1;
        for (unsigned i = 0; i < 4; ++i) {
            c = j->text[j->position++];
            if (!((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f')
                    || (c >= 'A' && c <= 'F'))) return -1;
        }
    }
    return -1;
}
static int parse_value(struct json *j, unsigned depth)
{
    whitespace(j);
    if (depth > 16 || j->position >= j->size || j->count >= TOKEN_CAP)
        return -1;
    unsigned index = j->count++;
    struct token *t = &j->tokens[index]; t->start = j->position;
    unsigned char c = j->text[j->position];
    if (c == '{' || c == '[') {
        int object = c == '{'; t->kind = object ? J_OBJECT : J_ARRAY;
        unsigned char end = object ? '}' : ']'; ++j->position; whitespace(j);
        if (j->position < j->size && j->text[j->position] == end) {
            ++j->position;
        } else for (;;) {
            if (object) {
                if (j->count >= TOKEN_CAP) return -1;
                struct token *key = &j->tokens[j->count++];
                key->kind = J_STRING; key->start = j->position;
                if (parse_string(j)) return -1;
                key->end = j->position; key->next = j->count;
                if (memchr(j->text + key->start, '\\', key->end - key->start))
                    return -1;
                whitespace(j);
                if (j->position >= j->size || j->text[j->position++] != ':')
                    return -1;
            }
            if (parse_value(j, depth + 1) < 0) return -1;
            whitespace(j);
            if (j->position >= j->size) return -1;
            c = j->text[j->position++];
            if (c == end) break;
            if (c != ',') return -1;
            whitespace(j);
        }
    } else if (c == '"') {
        t->kind = J_STRING; if (parse_string(j)) return -1;
    } else if (c == '-' || (c >= '0' && c <= '9')) {
        t->kind = J_NUMBER;
        if (c == '-' && ++j->position >= j->size) return -1;
        c = j->text[j->position];
        if (c == '0') ++j->position;
        else {
            if (c < '1' || c > '9') return -1;
            do { ++j->position; } while (j->position < j->size
                    && j->text[j->position] >= '0' && j->text[j->position] <= '9');
        }
        if (j->position < j->size && j->text[j->position] == '.') {
            size_t first = ++j->position;
            while (j->position < j->size && j->text[j->position] >= '0'
                    && j->text[j->position] <= '9') ++j->position;
            if (j->position == first) return -1;
        }
        if (j->position < j->size && (j->text[j->position] == 'e'
                                      || j->text[j->position] == 'E')) {
            ++j->position;
            if (j->position < j->size && (j->text[j->position] == '+'
                                          || j->text[j->position] == '-'))
                ++j->position;
            size_t first = j->position;
            while (j->position < j->size && j->text[j->position] >= '0'
                    && j->text[j->position] <= '9') ++j->position;
            if (j->position == first) return -1;
        }
    } else {
        const char *literal = c == 't' ? "true" : c == 'f' ? "false" : "null";
        size_t n = strlen(literal);
        if (j->size - j->position < n
                || memcmp(j->text + j->position, literal, n)) return -1;
        t->kind = c == 't' ? J_TRUE : c == 'f' ? J_FALSE : J_NULL;
        j->position += n;
    }
    t->end = j->position; t->next = j->count;
    return (int)index;
}
static int parse_json(struct json *j, const unsigned char *text, size_t n)
{
    memset(j, 0, sizeof(*j)); j->text = text; j->size = n;
    if (parse_value(j, 0) != 0) return -1;
    whitespace(j);
    return j->position == n && j->tokens[0].kind == J_OBJECT ? 0 : -1;
}
/* Duplicate requested field is rejected, rather than selecting one meaning. */
static int field(const struct json *j, unsigned object, const char *name)
{
    if (object >= j->count || j->tokens[object].kind != J_OBJECT) return -2;
    int found = -1; size_t length = strlen(name);
    for (unsigned i = object + 1; i < j->tokens[object].next;) {
        const struct token *key = &j->tokens[i]; unsigned value = i + 1;
        if (value >= j->count) return -2;
        if (key->end - key->start == length + 2
                && !memcmp(j->text + key->start + 1, name, length)) {
            if (found != -1) return -2;
            found = (int)value;
        }
        i = j->tokens[value].next;
    }
    return found;
}
static int boolean_field(const struct json *j, unsigned object, const char *name)
{
    int index = field(j, object, name);
    if (index < 0) return -1;
    return j->tokens[index].kind == J_TRUE ? 1
           : j->tokens[index].kind == J_FALSE ? 0 : -1;
}
static void body_json(unsigned char **p, size_t *bytes)
{
    if (*bytes >= 15 && !memcmp(*p, "3.5", 3)) { *p += 15; *bytes -= 15; }
}
static int extract_properties(unsigned char *text, size_t bytes,
                               struct properties *properties)
{
    struct json j;
    if (parse_json(&j, text, bytes)) return -1;
    int dps = field(&j, 0, "dps"), data = field(&j, 0, "data");
    if (dps == -2 || data == -2) return -1;
    if (data >= 0 && j.tokens[data].kind == J_OBJECT) {
        int nested = field(&j, (unsigned)data, "dps");
        if (nested == -2 || (dps >= 0 && nested >= 0)) return -1;
        if (nested >= 0) dps = nested;
    }
    if (dps < 0 || j.tokens[dps].kind != J_OBJECT) return -1;
    properties->indicator = boolean_field(&j, (unsigned)dps, "101");
    properties->osd = boolean_field(&j, (unsigned)dps, "104");
    properties->tracking = boolean_field(&j, (unsigned)dps, "161");
    return 0;
}
static int get_properties(struct session *s, struct properties *properties,
                           int64_t deadline)
{
    unsigned char response[CAP]; int result = -1;
    if (send_frame(s, 16, (const unsigned char *)"{}", 2, deadline)) goto done;
    for (unsigned i = 0; i < 8; ++i) {
        size_t bytes; uint32_t command;
        if (receive_frame(s, response, &bytes, &command, deadline)) goto done;
        if (command != 8 && command != 16) continue;
        if (bytes < 4 || get32(response)) goto done;
        unsigned char *text = response + 4; bytes -= 4; body_json(&text, &bytes);
        if (!extract_properties(text, bytes, properties)
                && properties->indicator >= 0 && properties->osd >= 0
                && properties->tracking >= 0) { result = 0; break; }
        if (command == 16) goto done; /* Malformed full response is definitive. */
    }
done:
    zeromem(response, sizeof(response));
    return result;
}

/* ----- Fixed control encodings. No caller supplies a DP number or raw JSON. */
enum operation { OP_INDICATOR, OP_OSD, OP_STOP, OP_UP, OP_RIGHT, OP_DOWN, OP_LEFT };
static int control_body(enum operation operation, int value,
                         unsigned char body[256], size_t *bytes)
{
    const char *dp, *encoded;
    switch (operation) {
    case OP_INDICATOR: dp = "101"; encoded = value ? "true" : "false"; break;
    case OP_OSD: dp = "104"; encoded = value ? "true" : "false"; break;
    case OP_STOP: dp = "116"; encoded = "true"; break;
    case OP_UP: dp = "119"; encoded = "\"0\""; break;
    case OP_RIGHT: dp = "119"; encoded = "\"2\""; break;
    case OP_DOWN: dp = "119"; encoded = "\"4\""; break;
    case OP_LEFT: dp = "119"; encoded = "\"6\""; break;
    default: return -1;
    }
    time_t wall = time(NULL);
    if (wall < 0) return -1;
    memcpy(body, "3.5\0\0\0\0\0\0\0\0\0\0\0\0", 15);
    int n = snprintf((char *)body + 15, 241,
        "{\"protocol\":5,\"t\":%lld,\"data\":{\"dps\":{\"%s\":%s}}}",
        (long long)wall, dp, encoded);
    if (n < 0 || n >= 241) return -1;
    *bytes = (size_t)n + 15;
    return 0;
}
static int control_ack(struct session *s, int64_t deadline)
{
    unsigned char response[CAP]; int result = -1;
    for (unsigned i = 0; i < 8; ++i) {
        size_t bytes; uint32_t command;
        if (receive_frame(s, response, &bytes, &command, deadline)) goto done;
        if (command != 13) continue;
        if (bytes < 4 || get32(response)) goto done;
        unsigned char *text = response + 4; bytes -= 4; body_json(&text, &bytes);
        if (bytes) {
            struct json j;
            if (parse_json(&j, text, bytes) || field(&j, 0, "error") != -1
                    || field(&j, 0, "Error") != -1
                    || field(&j, 0, "err") != -1) goto done;
        }
        result = 0; break;
    }
done:
    zeromem(response, sizeof(response));
    return result;
}
static int control_once(struct session *s, enum operation operation, int value,
                         int64_t send_deadline, int64_t ack_deadline)
{
    unsigned char body[256]; size_t bytes; int result = -1;
    if (!control_body(operation, value, body, &bytes)
            && !send_frame(s, 13, body, bytes, send_deadline))
        result = control_ack(s, ack_deadline);
    zeromem(body, sizeof(body));
    return result;
}

/* ----- Detached guardian: only it owns/reaps the disposable move child. ----- */
#ifdef YYOS_TEST_FIXTURE
#define LOCK_DIRECTORY "/tmp/yyos-controls-fixture.lock"
#define FIXTURE_JSON "true"
#else
#define LOCK_DIRECTORY "/run/lscamoflash-yyos-controls.lock"
#define FIXTURE_JSON "false"
#endif
struct guard_result {
    int ok, armed, move_acknowledged, stop_acknowledged, stop_attempts;
    const char *phase; /* Same address after fork; no exec or external payload. */
};
static int owner_gone(int fd, int timeout)
{
    struct pollfd p = {fd, POLLIN, 0};
    int result = poll(&p, 1, timeout);
    if (result < 0 && errno == EINTR) return 0;
    if (result < 0 || (p.revents & (POLLERR | POLLNVAL))) return 1;
    if (result > 0 && (p.revents & (POLLIN | POLLHUP))) return 1;
    return 0;
}
#ifdef YYOS_TEST_FIXTURE
static unsigned fixture_deferred_reaps;
#endif
static pid_t reap_owned(pid_t child, int *status)
{
#ifdef YYOS_TEST_FIXTURE
    if (fixture_deferred_reaps) { --fixture_deferred_reaps; return 0; }
#endif
    return waitpid(child, status, WNOHANG);
}
static int kill_and_reap(pid_t *owned_child, int *status)
{
    if (*owned_child < 0) return -1;
    pid_t reaped = reap_owned(*owned_child, status);
    if (reaped == *owned_child) { *owned_child = -1; return 0; }
    if (reaped < 0 && errno == ECHILD) { *owned_child = -1; return -1; }
    /* Never wait indefinitely before STOP. The PID remains ours until reaped;
     * SIGKILL prevents a suspended mover from returning to userspace later. */
    (void)kill(*owned_child, SIGKILL);
    for (unsigned i = 0; i < 5; ++i) {
        reaped = reap_owned(*owned_child, status);
        if (reaped == *owned_child) { *owned_child = -1; return 0; }
        if (reaped < 0 && errno == ECHILD) { *owned_child = -1; return -1; }
        (void)poll(NULL, 0, 2); /* Bounded relative wait, no clock dependency. */
    }
    return 1; /* Still owned: caller MUST STOP, retain the lock, then reap. */
}
static int stop_bounded(struct session *stop, const unsigned char local_key[16],
                          unsigned char first_frame[CAP], size_t first_bytes,
                          int *attempts)
{
#ifdef YYOS_TEST_FIXTURE
    if (getenv("YYOS_FIXTURE_FAIL_STOP_CLOCK")) fixture_fail_clock = 1;
#endif
    /* Submission is unconditional and precedes ALL clock/ACK/retry branches.
     * A scheduling delay or broken clock must never skip this prepared STOP. */
    ++*attempts;
    ssize_t sent = send(stop->fd, first_frame, first_bytes,
                        MSG_NOSIGNAL | MSG_DONTWAIT);
    int64_t begin = monotonic_ms();
    if (begin < 0) return -1; /* Submission attempted, acknowledgment unknown. */
    int64_t overall = begin + STOP_BUDGET_MS;
    if (sent == (ssize_t)first_bytes && !control_ack(stop, begin + 300))
        return 0;
    close_session(stop);
    for (unsigned i = 1; i < STOP_ATTEMPTS; ++i) {
        int64_t now = monotonic_ms();
        if (now < 0 || now >= overall) break;
        int64_t limit = now + 300;
        if (limit > overall) limit = overall;
        ++*attempts;
        if (open_session(stop, local_key, limit)) continue;
        if (!control_once(stop, OP_STOP, 1, limit, limit)) return 0;
        /* Partial frames/timeouts are never resumed on a possibly misaligned
         * stream. Only fixed idempotent STOP may be retried on a new session. */
        close_session(stop);
    }
    return -1;
}
static void jog_guard(unsigned char local_key[16], enum operation direction,
                        int owner, int report_fd)
{
    struct session stop = {.fd = -1}, move = {.fd = -1};
    struct properties current;
    unsigned char stop_body[256] = {0}, stop_frame[CAP] = {0};
    size_t stop_body_bytes = 0, stop_frame_bytes = 0;
    pid_t worker = -1; int worker_status = 0;
    struct guard_result result = {.phase = "guardian_setup"};
    alarm(12); signal(SIGHUP, SIG_IGN); signal(SIGPIPE, SIG_IGN);
    if (setsid() < 0 || clock_ready() || owner_gone(owner, 0)) goto finish;
    int64_t start = monotonic_ms();
    if (start < 0) goto finish;
    int64_t setup_deadline = start + 8000;
    result.phase = "guardian_stop_session";
    if (open_session(&stop, local_key, setup_deadline)) goto finish;
    result.phase = "guardian_move_session";
    if (open_session(&move, local_key, setup_deadline)) goto finish;
    result.phase = "tracking_precondition";
    if (get_properties(&move, &current, setup_deadline) || current.tracking != 0)
        goto finish;
    result.phase = "stop_preparation";
    if (control_body(OP_STOP, 1, stop_body, &stop_body_bytes)
            || pack_frame(stop_frame, &stop_frame_bytes, stop.key,
                          stop.sequence++, 13, stop_body, stop_body_bytes))
        goto finish;
    if (profile_matches()) { result.phase = "profile_changed_before_arm"; goto finish; }
    if (owner_gone(owner, 0)) { result.phase = "owner_lost_before_arm"; goto finish; }
    int64_t armed_at = monotonic_ms();
    if (armed_at < 0) goto finish;
    int64_t deadline = armed_at + JOG_MS;
    int64_t launch_cutoff = armed_at + LAUNCH_MS;
    result.armed = 1;
    /* From ARM onward every exit traverses STOP. No host command can cancel.
     * Do not leave a hard alarm that could terminate the guardian before STOP. */
    alarm(0);
    worker = fork();
    if (worker == 0) {
        close(owner); close(report_fd); close_session(&stop);
        zeromem(local_key, 16); zeromem(stop_body, sizeof(stop_body));
        zeromem(stop_frame, sizeof(stop_frame));
#ifdef YYOS_TEST_FIXTURE
        /* Only synthetic-key fixture builds contain this stale-worker case. */
        if (getenv("YYOS_FIXTURE_DELAY_WORKER")) (void)sleep_ms(350);
#endif
        int rc = control_once(&move, direction, 0, launch_cutoff, deadline);
        close_session(&move);
        _exit(rc ? 1 : 0);
    }
    close_session(&move);
    if (worker < 0) { result.phase = "move_fork_failed"; goto stop_now; }
    result.phase = "jog_deadline";
    for (;;) {
        int64_t now = monotonic_ms();
        if (now < 0) { result.phase = "jog_clock_failed"; break; }
        if (now >= deadline) break;
        if (owner_gone(owner, (int)(deadline - now))) {
            result.phase = "owner_lost_after_arm"; break;
        }
    }
stop_now:
#ifdef YYOS_TEST_FIXTURE
    if (getenv("YYOS_FIXTURE_DEFER_REAP")) fixture_deferred_reaps = 10;
#endif
    /* Kill/reap our helper before STOP. A suspended helper cannot resume later
     * and write a stale move after the guardian has gone away. */
    if (kill_and_reap(&worker, &worker_status)) {
        result.phase = "move_reap_deferred";
        /* STOP must not wait for a stalled child. Ownership is retained. */
    } else if (WIFEXITED(worker_status) && WEXITSTATUS(worker_status) == 0) {
        result.move_acknowledged = 1;
    }
    result.stop_acknowledged = !stop_bounded(&stop, local_key, stop_frame,
                                             stop_frame_bytes,
                                             &result.stop_attempts);
    result.ok = result.move_acknowledged && result.stop_acknowledged
                && !strcmp(result.phase, "jog_deadline");
finish:
    close_session(&move); close_session(&stop);
    zeromem(local_key, 16); zeromem(stop_body, sizeof(stop_body));
    zeromem(stop_frame, sizeof(stop_frame)); close(owner);
    /* A stalled child never outlives its guardian or releases our lock. STOP
     * was already attempted above. Keep ownership until WNOHANG proves exit;
     * no blocking waitpid and no further movement/setting writes occur here. */
    while (worker > 0) {
        result.ok = 0; result.phase = "move_reap_deferred";
        (void)kill(worker, SIGKILL);
        pid_t reaped = reap_owned(worker, &worker_status);
        if (reaped == worker || (reaped < 0 && errno == ECHILD)) worker = -1;
        else (void)poll(NULL, 0, 50);
    }
    ssize_t report_written = write(report_fd, &result, sizeof(result));
    (void)report_written; close(report_fd);
    (void)rmdir(LOCK_DIRECTORY);
    _exit(result.ok ? 0 : 1);
}
static int run_jog(unsigned char local_key[16], enum operation direction,
                    int *guardian_owns_lock)
{
    int owner[2], report[2];
    if (pipe2(owner, O_CLOEXEC)) return -1;
    if (pipe2(report, O_CLOEXEC)) { close(owner[0]); close(owner[1]); return -1; }
    pid_t guard = fork();
    if (guard < 0) {
        close(owner[0]); close(owner[1]); close(report[0]); close(report[1]);
        return -1;
    }
    if (!guard) {
        close(owner[1]); close(report[0]);
        jog_guard(local_key, direction, owner[0], report[1]);
    }
    *guardian_owns_lock = 1;
    zeromem(local_key, 16); close(owner[0]); close(report[1]);
    struct guard_result result; size_t got = 0;
    while (got < sizeof(result)) {
        ssize_t n = read(report[0], (unsigned char *)&result + got,
                         sizeof(result) - got);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) break;
        got += (size_t)n;
    }
    close(owner[1]); close(report[0]);
    int status; while (waitpid(guard, &status, 0) < 0 && errno == EINTR) {}
    if (got != sizeof(result)) {
        puts("{\"ok\":false,\"phase\":\"guardian_result_missing\"}");
        return 1;
    }
    printf("{\"ok\":%s,\"action\":\"jog\",\"jog_ms\":200,\"armed\":%s,"
           "\"move_acknowledged\":%s,\"stop_acknowledged\":%s,"
           "\"stop_attempts\":%d,\"phase\":\"%s\",\"fixture\":%s,"
           "\"physical_hard_deadline_proven\":false}\n",
           result.ok ? "true" : "false", result.armed ? "true" : "false",
           result.move_acknowledged ? "true" : "false",
           result.stop_acknowledged ? "true" : "false", result.stop_attempts,
           result.phase, FIXTURE_JSON);
    return result.ok ? 0 : 1;
}

/* ----- Narrow owner CLI. Status/readback output contains three booleans only. */
static int run_basic(const unsigned char key[16], int status_only,
                       enum operation operation, int value)
{
    struct session session = {.fd = -1}; struct properties before, after;
    int result = 1; const char *phase = "connect";
    int64_t now = monotonic_ms(); if (now < 0) goto done;
    int64_t deadline = now + 5000;
    if (open_session(&session, key, deadline)) goto done;
    if (operation == OP_STOP && !status_only) {
        phase = "profile_changed_before_stop";
        if (profile_matches()) goto done;
        phase = "stop_acknowledgment";
        if (control_once(&session, OP_STOP, 1, deadline, deadline)) goto done;
        printf("{\"ok\":true,\"action\":\"stop\","
               "\"stop_acknowledged\":true,\"fixture\":%s}\n", FIXTURE_JSON);
        result = 0; goto done;
    }
    phase = "current_status";
    if (get_properties(&session, &before, deadline)) goto done;
    if (status_only) {
        printf("{\"ok\":true,\"indicator\":%s,\"timestamp_osd\":%s,"
               "\"tracking\":%s,\"fixture\":%s}\n",
               before.indicator ? "true" : "false", before.osd ? "true" : "false",
               before.tracking ? "true" : "false", FIXTURE_JSON);
        result = 0; goto done;
    }
    int old = operation == OP_INDICATOR ? before.indicator : before.osd;
    if (old != value) {
        phase = "profile_changed_before_setting";
        if (profile_matches()) goto done;
        phase = "setting_acknowledgment";
        if (control_once(&session, operation, value, deadline, deadline)) goto done;
        /* Native command reports may queue an older full status on the write
         * socket. Authenticate a fresh read-only session for final readback;
         * never replay the setting write on a reconnect. */
        close_session(&session);
        phase = "setting_readback_connect";
        if (open_session(&session, key, deadline)) goto done;
        phase = "setting_readback";
        if (get_properties(&session, &after, deadline)
                || (operation == OP_INDICATOR ? after.indicator : after.osd) != value)
            goto done;
    }
    printf("{\"ok\":true,\"action\":\"%s\",\"previous\":%s,"
           "\"value\":%s,\"write_sent\":%s,\"readback_verified\":true,"
           "\"fixture\":%s}\n",
           operation == OP_INDICATOR ? "indicator" : "timestamp_osd",
           old ? "true" : "false", value ? "true" : "false",
           old == value ? "false" : "true", FIXTURE_JSON);
    result = 0;
done:
    close_session(&session);
    if (result) printf("{\"ok\":false,\"phase\":\"%s\"}\n", phase);
    return result;
}
int main(int argc, char **argv)
{
    enum operation operation = OP_STOP; int value = 0, status_only = 0, jog = 0;
    if (argc == 2 && !strcmp(argv[1], "status")) status_only = 1;
    else if (argc == 2 && !strcmp(argv[1], "stop")) operation = OP_STOP;
    else if (argc == 3 && (!strcmp(argv[1], "indicator")
                           || !strcmp(argv[1], "timestamp_osd"))) {
        operation = !strcmp(argv[1], "indicator") ? OP_INDICATOR : OP_OSD;
        if (!strcmp(argv[2], "true")) value = 1;
        else if (!strcmp(argv[2], "false")) value = 0;
        else return 2;
    } else if (argc == 3 && !strcmp(argv[1], "jog")) {
        jog = 1;
        if (!strcmp(argv[2], "up")) operation = OP_UP;
        else if (!strcmp(argv[2], "right")) operation = OP_RIGHT;
        else if (!strcmp(argv[2], "down")) operation = OP_DOWN;
        else if (!strcmp(argv[2], "left")) operation = OP_LEFT;
        else return 2;
    } else return 2;
    alarm(15); signal(SIGPIPE, SIG_IGN); signal(SIGCHLD, SIG_DFL);
    aes_index = register_cipher(&aes_desc); sha_index = register_hash(&sha256_desc);
    if (aes_index < 0 || sha_index < 0 || clock_ready() || profile_matches()) {
        puts("{\"ok\":false,\"phase\":\"profile_or_clock_guard\"}"); return 1;
    }
    unsigned char key[16] = {0};
    if (read_key(key)) {
        zeromem(key, sizeof(key));
        puts("{\"ok\":false,\"phase\":\"key_input\"}"); return 1;
    }
    if (mkdir(LOCK_DIRECTORY, 0700)) {
        zeromem(key, sizeof(key));
        puts("{\"ok\":false,\"phase\":\"existing_or_unavailable_lock\"}"); return 1;
    }
    int guardian_owns_lock = 0;
    int result = jog ? run_jog(key, operation, &guardian_owns_lock)
                     : run_basic(key, status_only, operation, value);
    zeromem(key, sizeof(key));
#ifdef YYOS_TEST_FIXTURE
    /* Simulate a new owner entering after guardian cleanup but before return. */
    if (guardian_owns_lock && getenv("YYOS_FIXTURE_NEW_LOCK_OWNER"))
        (void)mkdir(LOCK_DIRECTORY, 0700);
#endif
    /* Exactly one cleaner. A second owner's new lock must never be removed
     * after the detached guardian has already released our original lock. */
    if (!guardian_owns_lock) (void)rmdir(LOCK_DIRECTORY);
    return result < 0 ? 1 : result;
}
