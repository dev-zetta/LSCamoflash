/* Authenticated, fixed-action CGI adapter. No shell, configuration writes,
 * vendor IPC or key in argv/environment/output. Native CLI owns protocol/STOP. */
#define _GNU_SOURCE
#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <poll.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/statfs.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>
#ifndef YYOS_CONTROLS_CGI_FIXTURE_ROOT
#define ROOT "/mnt/sdcard/LSCamoflash-yyos"
#define DEADLINE_MS 30000
#else
#define ROOT YYOS_CONTROLS_CGI_FIXTURE_ROOT
#ifndef YYOS_CONTROLS_CGI_TEST_TIMEOUT_MS
#define YYOS_CONTROLS_CGI_TEST_TIMEOUT_MS 30000
#endif
#define DEADLINE_MS YYOS_CONTROLS_CGI_TEST_TIMEOUT_MS
#endif
#define HELPER ROOT "/bin/yyos-controls"
#define OUTPUT_CAP 4096
struct field { char key[40], text[80]; int kind, boolean; unsigned number; };
struct object { struct field fields[20]; unsigned count; };
static volatile sig_atomic_t interrupted;
static void interruption(int sig) { (void)sig; interrupted = 1; }
static int64_t now_ms(void) {
    struct timespec value;
    if (clock_gettime(CLOCK_MONOTONIC, &value) || value.tv_sec < 0 || value.tv_nsec < 0 || value.tv_nsec >= 1000000000) return -1;
    return (int64_t)value.tv_sec * 1000 + value.tv_nsec / 1000000;
}
static int body_read(char *data, unsigned bytes) {
    size_t used = 0; int64_t start = now_ms();
    if (start < 0 || !bytes || bytes > 256) return -1;
    while (used < bytes) {
        int64_t now = now_ms();
        if (interrupted || now < 0 || now - start >= 5000) return -1;
        struct pollfd p = {.fd = STDIN_FILENO, .events = POLLIN | POLLHUP};
        int ready = poll(&p, 1, (int)(5000 - (now - start)));
        if (ready < 0 && errno == EINTR) continue;
        if (ready <= 0) return -1;
        size_t remaining = (size_t)bytes - used;
        if (remaining > 256) return -1;
        ssize_t n = read(STDIN_FILENO, data + used, remaining);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0 || (size_t)n > remaining) return -1;
        used += (size_t)n;
    }
    return 0;
}
static int response(int code, const char *body) {
    const char *text = code == 200 ? "OK" : code == 400 ? "Bad Request" : code == 401 ? "Unauthorized" : code == 403 ? "Forbidden" : code == 405 ? "Method Not Allowed" : "Service Unavailable";
    printf("Status: %d %s\r\nContent-Type: application/json\r\nCache-Control: no-store\r\nX-Content-Type-Options: nosniff\r\n", code, text);
    if (code == 401) printf("WWW-Authenticate: Basic realm=\"LSCamoflash\"\r\n");
    if (code == 405) printf("Allow: GET, POST\r\n");
    printf("\r\n%s\n", body); fflush(stdout); return code == 200 ? 0 : 1;
}
static int failure(int code, const char *name) {
    char body[160]; snprintf(body, sizeof(body), "{\"ok\":false,\"error\":\"%s\"}", name); return response(code, body);
}
static void ws(const char **p, const char *end) { while (*p < end && **p && strchr(" \t\r\n", **p)) ++*p; }
static int string(const char **p, const char *end, char *out, size_t cap) {
    size_t size = 0;
    if (*p == end || *(*p)++ != '"') return -1;
    while (*p < end) {
        unsigned char c = (unsigned char)*(*p)++;
        if (c == '"') { out[size] = 0; return 0; }
        /* All accepted field names/actions are literal ASCII. Escaped aliases
         * are refused instead of creating two interpretations of a request. */
        if (c < 32 || c > 126 || c == '\\' || size + 1 >= cap) return -1;
        out[size++] = (char)c;
    }
    return -1;
}
static int object(const char *data, size_t bytes, struct object *out) {
    const char *p = data, *end = data + bytes;
    memset(out, 0, sizeof(*out)); ws(&p, end);
    if (p == end || *p++ != '{') return -1;
    ws(&p, end);
    if (p < end && *p == '}') ++p;
    else for (;;) {
        if (out->count >= 20) return -1;
        struct field *f = &out->fields[out->count];
        if (string(&p, end, f->key, sizeof(f->key))) return -1;
        for (unsigned i = 0; i < out->count; i++) if (!strcmp(out->fields[i].key, f->key)) return -1;
        ws(&p, end); if (p == end || *p++ != ':') return -1; ws(&p, end);
        if (p < end && *p == '"') { f->kind = 1; if (string(&p, end, f->text, sizeof(f->text))) return -1; }
        else if (end - p >= 4 && !memcmp(p, "true", 4)) { f->kind = 2; f->boolean = 1; p += 4; }
        else if (end - p >= 5 && !memcmp(p, "false", 5)) { f->kind = 2; p += 5; }
        else if (p < end && *p >= '0' && *p <= '9') {
            f->kind = 3; const char *first = p;
            do { if (f->number > 100000) return -1; f->number = f->number * 10 + (unsigned)(*p++ - '0'); } while (p < end && *p >= '0' && *p <= '9');
            if (p - first > 1 && *first == '0') return -1;
        } else return -1;
        out->count++; ws(&p, end);
        if (p == end) return -1;
        if (*p == '}') { ++p; break; }
        if (*p++ != ',') return -1;
        ws(&p, end);
    }
    ws(&p, end); return p == end ? 0 : -1;
}
static const struct field *get(const struct object *o, const char *key, int kind) {
    for (unsigned i = 0; i < o->count; i++) if (!strcmp(o->fields[i].key, key)) return o->fields[i].kind == kind ? &o->fields[i] : NULL;
    return NULL;
}
static int boolean(const struct object *o, const char *key) { const struct field *f = get(o, key, 2); return f ? f->boolean : -1; }
static int allowed(const struct object *o, const char *names) {
    for (unsigned i = 0; i < o->count; i++) {
        char needle[48]; snprintf(needle, sizeof(needle), " %s ", o->fields[i].key);
        if (!strstr(names, needle)) return 0;
    }
    return 1;
}
static int host_valid(const char *host) {
    struct in_addr address; char ip[16], canonical[16]; size_t n;
    if (!host || !(n = strlen(host)) || n < 6 || n > 20 || strcmp(host + n - 5, ":8080")) return 0;
    if (n - 5 >= sizeof(ip)) return 0;
    memcpy(ip, host, n - 5); ip[n - 5] = 0;
    if (inet_pton(AF_INET, ip, &address) != 1 || !inet_ntop(AF_INET, &address, canonical, sizeof(canonical)) || strcmp(ip, canonical)) return 0;
    uint32_t v = ntohl(address.s_addr);
    return (v >> 24) == 10 || (v >> 20) == 0xac1 || (v >> 16) == 0xc0a8;
}
static int root_fd(void) {
    char copy[PATH_MAX], *save, *name; int fd, next;
    if (strlen(ROOT) >= sizeof(copy) || ROOT[0] != '/') return -1;
    strcpy(copy, ROOT); fd = open("/", O_RDONLY | O_DIRECTORY | O_CLOEXEC); if (fd < 0) return -1;
    for (name = strtok_r(copy, "/", &save); name; name = strtok_r(NULL, "/", &save)) {
        if (!strcmp(name, ".") || !strcmp(name, "..")) { close(fd); return -1; }
        next = openat(fd, name, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC); close(fd); fd = next; if (fd < 0) return -1;
    }
#ifndef YYOS_CONTROLS_CGI_FIXTURE_ROOT
    struct stat st, device; struct statfs fs;
    if (fstat(fd, &st) || fstatfs(fd, &fs) || fs.f_type != 0x4d44 || lstat("/dev/mmcblk0p1", &device) || !S_ISBLK(device.st_mode) || st.st_dev != device.st_rdev) { close(fd); return -1; }
#endif
    return fd;
}
static int read_key(int root, unsigned char key[16]) {
    struct stat st, parent; unsigned char buffer[18]; ssize_t bytes;
    int fd = openat(root, "native-control.key", O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC);
    if (fd < 0) return errno == ENOENT ? 1 : -1;
    int good = !fstat(root, &parent) && !fstat(fd, &st) && S_ISREG(st.st_mode) && st.st_nlink == 1 && st.st_dev == parent.st_dev && (st.st_size == 16 || st.st_size == 17);
    bytes = good ? read(fd, buffer, sizeof(buffer)) : -1; close(fd);
    if (bytes != 16 && !(bytes == 17 && buffer[16] == '\n')) good = 0;
    for (unsigned i = 0; good && i < 16; i++) if (buffer[i] < 33 || buffer[i] > 126) good = 0;
    if (good) memcpy(key, buffer, 16);
    volatile unsigned char *p = buffer; for (unsigned i = 0; i < sizeof(buffer); i++) p[i] = 0;
    return good ? 0 : -1;
}
static int helper_fd(int root) {
    struct stat st, parent; int bin = openat(root, "bin", O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
    if (bin < 0) return -1;
    int fd = openat(bin, "yyos-controls", O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC); close(bin);
    if (fd < 0) return -1;
    if (fstat(root, &parent) || fstat(fd, &st) || !S_ISREG(st.st_mode) || st.st_nlink != 1 || st.st_dev != parent.st_dev || !(st.st_mode & 0111) || st.st_size <= 0 || st.st_size > 1024 * 1024) { close(fd); return -1; }
    return fd;
}
static void reap(pid_t child) {
    int status;
    for (unsigned i = 0; i < 40; i++) {
        pid_t result = waitpid(child, &status, WNOHANG);
        if (result == child || (result < 0 && errno == ECHILD)) return;
        if (i == 0) (void)kill(child, SIGTERM);
        if (i == 4) (void)kill(child, SIGKILL);
        (void)poll(NULL, 0, 25);
    }
}
static int run(int helper, unsigned char key[16], const char *action, const char *value, char output[OUTPUT_CAP + 1]) {
    int input[2], result[2], status = 0; size_t used = 0; pid_t child;
    if (pipe2(input, O_CLOEXEC)) return -1;
    if (pipe2(result, O_CLOEXEC)) { close(input[0]); close(input[1]); return -1; }
    child = fork();
    if (child < 0) { close(input[0]); close(input[1]); close(result[0]); close(result[1]); return -1; }
    if (child == 0) {
        int null = open("/dev/null", O_RDWR | O_CLOEXEC);
        close(input[1]); close(result[0]);
        if (null < 0 || dup2(input[0], 0) < 0 || dup2(result[1], 1) < 0 || dup2(null, 2) < 0) _exit(126);
        close(input[0]); close(result[1]); close(null);
        char *args[] = {HELPER, (char *)action, (char *)value, NULL};
        char *environment[] = {"PATH=/bin:/sbin:/usr/bin:/usr/sbin", "LC_ALL=C", NULL};
        if (!value) args[2] = NULL;
        fexecve(helper, args, environment); _exit(126);
    }
    close(input[0]); close(result[1]);
    ssize_t sent = write(input[1], key, 16); close(input[1]);
    volatile unsigned char *secret = key; for (unsigned i = 0; i < 16; i++) secret[i] = 0;
    int64_t start = now_ms();
    int good = sent == 16 && start >= 0;
    while (good) {
        int64_t now = now_ms();
        if (interrupted || now < 0 || now - start >= DEADLINE_MS) { good = 0; break; }
        struct pollfd p = {.fd = result[0], .events = POLLIN | POLLHUP};
        int ready = poll(&p, 1, (int)(DEADLINE_MS - (now - start)));
        if (ready < 0 && errno == EINTR) continue;
        if (ready <= 0) { good = 0; break; }
        ssize_t n = read(result[0], output + used, OUTPUT_CAP + 1 - used);
        if (n < 0 && errno == EINTR) continue;
        if (n < 0) { good = 0; break; }
        if (!n) break;
        used += (size_t)n;
        if (used > OUTPUT_CAP) { good = 0; break; }
    }
    close(result[0]);
    if (!good) { reap(child); return -1; }
    int64_t until = now_ms() + 1000;
    for (;;) {
        pid_t done = waitpid(child, &status, WNOHANG);
        if (done == child) break;
        if (done < 0 || interrupted || now_ms() < 0 || now_ms() >= until) { reap(child); return -1; }
        (void)poll(NULL, 0, 10);
    }
    if (memchr(output, 0, used)) return -1;
    output[used] = 0;
    return WIFEXITED(status) && WEXITSTATUS(status) == 0 ? 0 : 1;
}
int main(void) {
    const char *method = getenv("REQUEST_METHOD"), *user = getenv("REMOTE_USER"), *host = getenv("HTTP_HOST"), *query = getenv("QUERY_STRING");
    unsigned char key[16] = {0}; char data[257], output[OUTPUT_CAP + 1]; const char *action = "status", *value = NULL;
    struct object request, answer; int root, helper, result;
    signal(SIGPIPE, SIG_IGN);
    struct sigaction interrupted_action = {.sa_handler = interruption};
    sigemptyset(&interrupted_action.sa_mask);
    sigaction(SIGTERM, &interrupted_action, NULL); sigaction(SIGINT, &interrupted_action, NULL); sigaction(SIGALRM, &interrupted_action, NULL);
    alarm(40);
    if (!user || !*user || strlen(user) > 32) return failure(401, "authentication_required");
    for (const char *p = user; *p; p++) if ((unsigned char)*p < 33 || (unsigned char)*p > 126) return failure(401, "authentication_required");
    if (!method || (strcmp(method, "GET") && strcmp(method, "POST"))) return failure(405, "fixed_actions_only");
    if (!host_valid(host) || (query && *query)) return failure(400, "invalid_request_target");
    if (!strcmp(method, "POST")) {
        const char *origin = getenv("HTTP_ORIGIN"), *type = getenv("CONTENT_TYPE"), *header = getenv("HTTP_X_LSCAMOFLASH_REQUEST"), *length = getenv("CONTENT_LENGTH");
        char expected[40]; snprintf(expected, sizeof(expected), "http://%s", host);
        if (!origin || strcmp(origin, expected) || !header || strcmp(header, "controls-v1")) return failure(403, "same_origin_required");
        if (!type || strcmp(type, "application/json") || !length || !*length || strlen(length) > 3) return failure(400, "invalid_request_body");
        unsigned bytes = 0; for (const char *p = length; *p; p++) { if (*p < '0' || *p > '9') return failure(400, "invalid_request_body"); bytes = bytes * 10 + (unsigned)(*p - '0'); }
        if (!bytes || bytes > 256 || (length[0] == '0' && length[1]) || body_read(data, bytes) || object(data, bytes, &request)) return failure(400, "invalid_request_body");
        const struct field *a = get(&request, "action", 1);
        if (!a) return failure(400, "invalid_action");
        action = a->text;
        if (!strcmp(action, "indicator") || !strcmp(action, "timestamp_osd")) {
            int v = boolean(&request, "value");
            if (request.count != 2 || v < 0 || !allowed(&request, " action  value ")) return failure(400, "invalid_action");
            value = v ? "true" : "false";
        } else if (!strcmp(action, "jog")) {
            const struct field *d = get(&request, "direction", 1);
            if (request.count != 2 || !d || !allowed(&request, " action  direction ") || (strcmp(d->text, "up") && strcmp(d->text, "right") && strcmp(d->text, "down") && strcmp(d->text, "left"))) return failure(400, "invalid_action");
            value = d->text;
        } else if (strcmp(action, "stop") || request.count != 1) return failure(400, "invalid_action");
    }
    root = root_fd(); if (root < 0) return failure(503, "runtime_storage_unavailable");
    result = read_key(root, key);
    if (result == 1) { close(root); return !strcmp(method, "GET") ? response(200, "{\"ok\":true,\"configured\":false}") : failure(503, "controls_not_configured"); }
    if (result < 0) { close(root); return failure(503, "invalid_private_control_key"); }
    helper = helper_fd(root); close(root);
    if (helper < 0) return failure(503, "control_helper_unavailable");
    result = run(helper, key, action, value, output); close(helper);
    if (result < 0 || object(output, strlen(output), &answer) || !allowed(&answer, " ok  indicator  timestamp_osd  tracking  fixture  action  previous  value  write_sent  readback_verified  stop_acknowledged  jog_ms  armed  move_acknowledged  stop_attempts  phase  physical_hard_deadline_proven ") || boolean(&answer, "fixture") == 1) return failure(503, "invalid_control_response");
    if (result || boolean(&answer, "ok") != 1) return failure(503, "control_operation_failed");
    const struct field *reply_action = get(&answer, "action", 1);
    if (boolean(&answer, "fixture") != 0 || (strcmp(action, "status") && (!reply_action || strcmp(reply_action->text, action)))) return failure(503, "invalid_control_response");
    if (!strcmp(action, "status")) {
        int led = boolean(&answer, "indicator"), osd = boolean(&answer, "timestamp_osd"), tracking = boolean(&answer, "tracking");
        if (led < 0 || osd < 0 || tracking < 0) return failure(503, "invalid_control_response");
        snprintf(data, sizeof(data), "{\"ok\":true,\"configured\":true,\"indicator\":%s,\"timestamp_osd\":%s,\"tracking\":%s}", led ? "true" : "false", osd ? "true" : "false", tracking ? "true" : "false");
    } else if (!strcmp(action, "indicator") || !strcmp(action, "timestamp_osd")) {
        if (boolean(&answer, "value") != !strcmp(value, "true") || boolean(&answer, "readback_verified") != 1) return failure(503, "invalid_control_response");
        snprintf(data, sizeof(data), "{\"ok\":true,\"configured\":true,\"action\":\"%s\",\"value\":%s,\"readback_verified\":true}", action, value);
    } else if (!strcmp(action, "stop")) {
        if (boolean(&answer, "stop_acknowledged") != 1) return failure(503, "invalid_control_response");
        strcpy(data, "{\"ok\":true,\"configured\":true,\"action\":\"stop\",\"stop_acknowledged\":true}");
    } else {
        const struct field *ms = get(&answer, "jog_ms", 3), *attempts = get(&answer, "stop_attempts", 3);
        if (!ms || ms->number != 200 || !attempts || !attempts->number || attempts->number > 3 || boolean(&answer, "armed") != 1 || boolean(&answer, "move_acknowledged") != 1 || boolean(&answer, "stop_acknowledged") != 1 || boolean(&answer, "physical_hard_deadline_proven") != 0) return failure(503, "invalid_control_response");
        strcpy(data, "{\"ok\":true,\"configured\":true,\"action\":\"jog\",\"jog_ms\":200,\"stop_acknowledged\":true,\"physical_hard_deadline_proven\":false}");
    }
    return response(200, data);
}
