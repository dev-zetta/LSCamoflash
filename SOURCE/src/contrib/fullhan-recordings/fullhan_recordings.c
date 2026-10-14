#define _GNU_SOURCE
#define _FILE_OFFSET_BITS 64
#include <sys/types.h>
#include <sys/stat.h>
#include <sys/statfs.h>
#include <fcntl.h>
#include <dirent.h>
#include <unistd.h>
#include <stdint.h>
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <limits.h>
#include <signal.h>

/* CGI only: no shell, subprocess, writes, mounts, or vendor application access. */
#ifndef FULLHAN_RECORDINGS_FIXTURE_ROOT
#define RECORDINGS_ROOT "/mnt/DCIM"
#else
/* Only separately compiled offline fixtures contain a different root. */
#define RECORDINGS_ROOT FULLHAN_RECORDINGS_FIXTURE_ROOT
#endif
#define MAX_QUERY 4096
#define MAX_PAGE 100
#define MAX_DAYS 1024
#define MAX_FILES 4096
#define MAX_SCAN 8192
#define MAX_FILE_BYTES UINT64_C(4294967295)

struct query {
    char action[16], day[11], file[34];
    unsigned offset, limit, seen;
};
struct recording { char name[34]; uint64_t bytes; };
static int head_request;
static dev_t card_device;
static unsigned scanned;
static int scan_truncated;

static void json_string(const char *s) {
    const unsigned char *p = (const unsigned char *)s;
    putchar('"');
    for (; *p; p++) {
        if (*p == '"' || *p == '\\') { putchar('\\'); putchar(*p); }
        else if (*p < 32 || *p >= 127) printf("\\u%04x", (unsigned)*p);
        else putchar(*p);
    }
    putchar('"');
}
static const char *status_text(int status) {
    switch (status) {
    case 200: return "OK";
    case 206: return "Partial Content";
    case 400: return "Bad Request";
    case 401: return "Unauthorized";
    case 403: return "Forbidden";
    case 404: return "Not Found";
    case 405: return "Method Not Allowed";
    case 416: return "Range Not Satisfiable";
    default: return "Service Unavailable";
    }
}
static void json_headers(int status) {
    printf("Status: %d %s\r\nContent-Type: application/json\r\n"
           "Cache-Control: no-store\r\nX-Content-Type-Options: nosniff\r\n",
           status, status_text(status));
    if (status == 405) printf("Allow: GET, HEAD\r\n");
    if (status == 401) printf("WWW-Authenticate: Basic realm=\"LSCamoflash\"\r\n");
}
static int error_response(int status, const char *message, uint64_t size) {
    json_headers(status);
    if (status == 416) printf("Content-Range: bytes */%" PRIu64 "\r\n", size);
    printf("\r\n");
    if (!head_request) { printf("{\"error\":"); json_string(message); printf("}\n"); }
    fflush(stdout);
    return 1;
}
static int path_error(void) {
    if (errno == ENOENT) return error_response(404, "Recording path not found", 0);
    if (errno == ELOOP || errno == ENOTDIR || errno == EXDEV || errno == EPERM)
        return error_response(403, "Recording path is not allowed", 0);
    return error_response(503, "Recording storage unavailable", 0);
}
static int digits(const char *p, size_t n) {
    size_t i;
    for (i = 0; i < n; i++) if (p[i] < '0' || p[i] > '9') return 0;
    return 1;
}
static unsigned decimal(const char *p, size_t n) {
    unsigned value = 0;
    size_t i;
    for (i = 0; i < n; i++) value = value * 10 + (unsigned)(p[i] - '0');
    return value;
}
static int calendar(unsigned y, unsigned m, unsigned d) {
    static const unsigned days[] = {0,31,28,31,30,31,30,31,31,30,31,30,31};
    unsigned last;
    if (y < 1 || y > 9999 || m < 1 || m > 12) return 0;
    last = days[m] + (m == 2 && y % 4 == 0 && (y % 100 != 0 || y % 400 == 0));
    return d >= 1 && d <= last;
}
static int valid_day(const char *day) {
    return strlen(day) == 10 && day[4] == '-' && day[7] == '-'
        && digits(day, 4) && digits(day + 5, 2) && digits(day + 8, 2)
        && calendar(decimal(day, 4), decimal(day + 5, 2), decimal(day + 8, 2));
}
static int timestamp(const char *s) {
    return digits(s, 14) && calendar(decimal(s, 4), decimal(s + 4, 2), decimal(s + 6, 2))
        && decimal(s + 8, 2) <= 23 && decimal(s + 10, 2) <= 59 && decimal(s + 12, 2) <= 59;
}
static int valid_file(const char *name) {
    return strlen(name) == 33 && name[14] == '-' && strcmp(name + 29, ".mp4") == 0
        && timestamp(name) && timestamp(name + 15) && strncmp(name, name + 15, 14) <= 0;
}
static int hex_digit(unsigned char c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}
static int decode(char *out, size_t capacity, const char *s, size_t length) {
    size_t i, used = 0;
    for (i = 0; i < length; i++) {
        unsigned char c = (unsigned char)s[i];
        if (c == '%') {
            int a, b;
            if (i + 2 >= length || (a = hex_digit((unsigned char)s[i+1])) < 0
                || (b = hex_digit((unsigned char)s[i+2])) < 0) return 0;
            c = (unsigned char)((a << 4) | b); i += 2;
        } else if (c == '+') c = ' ';
        if (c < 32 || c >= 127 || used + 1 >= capacity) return 0;
        out[used++] = (char)c;
    }
    out[used] = '\0';
    return 1;
}
static int unsigned_value(const char *s, uint64_t *out) {
    uint64_t value = 0;
    if (!*s) return 0;
    for (; *s; s++) {
        unsigned d;
        if (*s < '0' || *s > '9') return 0;
        d = (unsigned)(*s - '0');
        if (value > (UINT64_MAX - d) / 10) return 0;
        value = value * 10 + d;
    }
    *out = value;
    return 1;
}
static int parse_query(struct query *q) {
    const char *s = getenv("QUERY_STRING");
    memset(q, 0, sizeof(*q)); strcpy(q->action, "list"); q->limit = MAX_PAGE;
    if (!s || !*s) return 1;
    if (strlen(s) > MAX_QUERY) return 0;
    while (*s) {
        const char *end = strchr(s, '&'), *equal;
        size_t length = end ? (size_t)(end - s) : strlen(s);
        char key[16], value[64];
        unsigned bit;
        uint64_t number;
        equal = memchr(s, '=', length);
        if (!equal || !decode(key, sizeof(key), s, (size_t)(equal-s))
            || !decode(value, sizeof(value), equal+1, length-(size_t)(equal+1-s))) return 0;
        if (strcmp(key, "action") == 0) bit = 1;
        else if (strcmp(key, "day") == 0) bit = 2;
        else if (strcmp(key, "file") == 0) bit = 4;
        else if (strcmp(key, "offset") == 0) bit = 8;
        else if (strcmp(key, "limit") == 0) bit = 16;
        else return 0;
        if (q->seen & bit) return 0;
        q->seen |= bit;
        if (bit == 1) {
            if (strcmp(value, "list") && strcmp(value, "download")) return 0;
            strcpy(q->action, value);
        } else if (bit == 2) {
            if (!valid_day(value)) return 0;
            strcpy(q->day, value);
        } else if (bit == 4) {
            if (!valid_file(value)) return 0;
            strcpy(q->file, value);
        } else {
            if (!unsigned_value(value, &number)) return 0;
            if (bit == 8) { if (number > MAX_FILES) return 0; q->offset = (unsigned)number; }
            else { if (number < 1 || number > MAX_PAGE) return 0; q->limit = (unsigned)number; }
        }
        if (!end) break;
        s = end + 1;
        if (!*s) return 0;
    }
    if (!strcmp(q->action, "download")) return (q->seen & 6) == 6 && !(q->seen & 24);
    return !(q->seen & 4);
}
static int open_chain(const char *path) {
    char copy[PATH_MAX], *name, *save;
    int fd, next;
    if (path[0] != '/' || strlen(path) >= sizeof(copy)) { errno = EPERM; return -1; }
    strcpy(copy, path);
    fd = open("/", O_RDONLY | O_DIRECTORY | O_CLOEXEC);
    if (fd < 0) return -1;
    for (name = strtok_r(copy, "/", &save); name; name = strtok_r(NULL, "/", &save)) {
        if (!strcmp(name, ".") || !strcmp(name, "..")) { close(fd); errno = EPERM; return -1; }
        next = openat(fd, name, O_RDONLY | O_DIRECTORY | O_CLOEXEC | O_NOFOLLOW);
        if (next < 0) { int e = errno; close(fd); errno = e; return -1; }
        close(fd); fd = next;
    }
    return fd;
}
static int open_root(void) {
    int fd = open_chain(RECORDINGS_ROOT);
    struct stat st;
    if (fd < 0) return -1;
    if (fstat(fd, &st)) { int e = errno; close(fd); errno = e; return -1; }
    card_device = st.st_dev;
#ifndef FULLHAN_RECORDINGS_FIXTURE_ROOT
    {
        struct stat card, mmc;
        struct statfs fs;
        int card_fd = open_chain("/mnt");
        int good = card_fd >= 0 && !fstat(card_fd, &card) && !fstatfs(card_fd, &fs)
            && fs.f_type == 0x4d44 && card.st_dev == st.st_dev
            && !lstat("/dev/mmcblk0p1", &mmc) && S_ISBLK(mmc.st_mode) && mmc.st_rdev == card.st_dev;
        if (card_fd >= 0) close(card_fd);
        if (!good) { close(fd); errno = EPERM; return -1; }
    }
#endif
    return fd;
}
static int open_directory(int parent, const char *name) {
    int fd;
    struct stat before, after;
    if (fstatat(parent, name, &before, AT_SYMLINK_NOFOLLOW)) return -1;
    if (!S_ISDIR(before.st_mode) || before.st_dev != card_device) { errno = EPERM; return -1; }
    fd = openat(parent, name, O_RDONLY | O_DIRECTORY | O_CLOEXEC | O_NOFOLLOW);
    if (fd < 0) return -1;
    if (fstat(fd, &after) || after.st_dev != before.st_dev || after.st_ino != before.st_ino) {
        close(fd); errno = EPERM; return -1;
    }
    return fd;
}
static int day_directory(int root, const char *day) {
    char year[5], month[3], date[3];
    int y, m, d;
    memcpy(year, day, 4); year[4] = 0;
    memcpy(month, day+5, 2); month[2] = 0;
    memcpy(date, day+8, 2); date[2] = 0;
    y = open_directory(root, year); if (y < 0) return -1;
    m = open_directory(y, month); close(y); if (m < 0) return -1;
    d = open_directory(m, date); close(m); return d;
}
static int scan_entry(const char *name) {
    if (!strcmp(name, ".") || !strcmp(name, "..")) return 0;
    if (scanned >= MAX_SCAN) { scan_truncated = 1; return -1; }
    scanned++;
    return 1;
}
static struct dirent *next_entry(DIR *directory, int *failed) {
    struct dirent *entry;
    errno = 0;
    entry = readdir(directory);
    if (!entry && errno) *failed = 1;
    return entry;
}
static int days_descending(const void *a, const void *b) { return strcmp(b, a); }
static int files_descending(const void *a, const void *b) {
    return strcmp(((const struct recording *)b)->name, ((const struct recording *)a)->name);
}
static void page_end(const struct query *q, unsigned count) {
    unsigned end = q->offset > count ? count : q->offset;
    if (q->limit < count - end) end += q->limit; else end = count;
    printf("],\"offset\":%u,\"limit\":%u,\"next_offset\":", q->offset, q->limit);
    if (end < count) printf("%u", end); else printf("null");
    printf(",\"scan_truncated\":%s}\n", scan_truncated ? "true" : "false");
}
static int list_days(int root, const struct query *q) {
    char (*days)[11] = calloc(MAX_DAYS, 11);
    DIR *years = NULL;
    struct dirent *ye;
    unsigned count = 0, i, end;
    int failed = 0;
    if (!days || !(years = fdopendir(dup(root)))) { free(days); return error_response(503, "Recording inventory unavailable", 0); }
    while ((ye = next_entry(years, &failed)) != NULL && !scan_truncated) {
        int check = scan_entry(ye->d_name), y;
        DIR *months;
        struct dirent *mo;
        char year[5];
        if (check < 0) break;
        if (!check || strlen(ye->d_name) != 4 || !digits(ye->d_name, 4)) continue;
        memcpy(year, ye->d_name, 5);
        y = open_directory(root, year); if (y < 0) continue;
        months = fdopendir(y); if (!months) { close(y); failed = 1; break; }
        while ((mo = next_entry(months, &failed)) != NULL && !scan_truncated) {
            int m;
            DIR *dates;
            struct dirent *da;
            char month[3];
            check = scan_entry(mo->d_name); if (check < 0) break;
            if (!check || strlen(mo->d_name) != 2 || !digits(mo->d_name, 2)
                || decimal(mo->d_name, 2) < 1 || decimal(mo->d_name, 2) > 12) continue;
            memcpy(month, mo->d_name, 3);
            m = open_directory(dirfd(months), month); if (m < 0) continue;
            dates = fdopendir(m); if (!dates) { close(m); failed = 1; break; }
            while ((da = next_entry(dates, &failed)) != NULL && !scan_truncated) {
                char day[11];
                int d;
                check = scan_entry(da->d_name); if (check < 0) break;
                if (!check || strlen(da->d_name) != 2 || !digits(da->d_name, 2)) continue;
                memcpy(day, year, 4); day[4] = '-';
                memcpy(day+5, month, 2); day[7] = '-';
                memcpy(day+8, da->d_name, 2); day[10] = 0;
                if (!valid_day(day)) continue;
                d = open_directory(dirfd(dates), da->d_name); if (d < 0) continue;
                close(d);
                if (count == MAX_DAYS) { scan_truncated = 1; break; }
                memcpy(days[count++], day, 11);
            }
            closedir(dates);
            if (failed) break;
        }
        closedir(months);
        if (failed) break;
    }
    closedir(years);
    if (failed) { free(days); return error_response(503, "Recording inventory unavailable", 0); }
    qsort(days, count, 11, days_descending);
    json_headers(200); printf("\r\n");
    if (!head_request) {
        printf("{\"kind\":\"days\",\"days\":[");
        end = q->offset > count ? count : q->offset;
        for (i = end; i < count && i - end < q->limit; i++) {
            if (i != end) putchar(',');
            printf("{\"name\":"); json_string(days[i]); putchar('}');
        }
        page_end(q, count);
    }
    free(days);
    return fflush(stdout) == 0 ? 0 : 1;
}
static int safe_recording(int directory, const char *name, struct stat *st) {
    return valid_file(name) && !fstatat(directory, name, st, AT_SYMLINK_NOFOLLOW)
        && S_ISREG(st->st_mode) && st->st_nlink == 1 && st->st_dev == card_device
        && st->st_size > 0 && (uint64_t)st->st_size <= MAX_FILE_BYTES;
}
static int list_files(int root, const struct query *q) {
    struct recording *files = calloc(MAX_FILES, sizeof(*files));
    struct dirent *entry;
    int directory = day_directory(root, q->day), failed = 0;
    DIR *list;
    unsigned count = 0, i, end;
    if (directory < 0) { free(files); return path_error(); }
    if (!files || !(list = fdopendir(directory))) { close(directory); free(files); return error_response(503, "Recording inventory unavailable", 0); }
    while ((entry = next_entry(list, &failed)) != NULL) {
        struct stat st;
        int check = scan_entry(entry->d_name);
        if (check < 0) break;
        if (!check || !safe_recording(dirfd(list), entry->d_name, &st)) continue;
        if (count == MAX_FILES) { scan_truncated = 1; break; }
        strcpy(files[count].name, entry->d_name); files[count++].bytes = (uint64_t)st.st_size;
    }
    closedir(list);
    if (failed) { free(files); return error_response(503, "Recording inventory unavailable", 0); }
    qsort(files, count, sizeof(*files), files_descending);
    json_headers(200); printf("\r\n");
    if (!head_request) {
        printf("{\"kind\":\"files\",\"day\":"); json_string(q->day); printf(",\"files\":[");
        end = q->offset > count ? count : q->offset;
        for (i = end; i < count && i - end < q->limit; i++) {
            char url[160];
            if (i != end) putchar(',');
            printf("{\"name\":"); json_string(files[i].name);
            printf(",\"bytes\":%" PRIu64 ",\"download\":", files[i].bytes);
            snprintf(url, sizeof(url), "recordings.cgi?action=download&day=%s&file=%s", q->day, files[i].name);
            json_string(url); putchar('}');
        }
        page_end(q, count);
    }
    free(files);
    return fflush(stdout) == 0 ? 0 : 1;
}
static int byte_range(const char *value, uint64_t size, uint64_t *first, uint64_t *last) {
    char buffer[129], *dash;
    uint64_t a, b;
    *first = 0; *last = size - 1;
    if (!value || !*value) return 200;
    if (strlen(value) >= sizeof(buffer) || strncmp(value, "bytes=", 6)) return 416;
    strcpy(buffer, value + 6);
    dash = strchr(buffer, '-');
    if (!dash || strchr(dash + 1, '-')) return 416;
    *dash++ = 0;
    if (!buffer[0]) {
        if (!unsigned_value(dash, &b) || b == 0) return 416;
        *first = b >= size ? 0 : size - b;
    } else {
        if (!unsigned_value(buffer, &a) || a >= size) return 416;
        *first = a;
        if (*dash) {
            if (!unsigned_value(dash, &b) || b < a) return 416;
            *last = b >= size ? size - 1 : b;
        }
    }
    return 206;
}
static int write_all(const char *buffer, size_t length) {
    while (length) {
        ssize_t n = write(STDOUT_FILENO, buffer, length);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) return 0;
        buffer += n; length -= (size_t)n;
    }
    return 1;
}
static int download(int root, const struct query *q) {
    struct stat before, after;
    int directory = day_directory(root, q->day), fd, status;
    uint64_t first, last, remaining;
    char buffer[16384];
    if (directory < 0) return path_error();
    if (!safe_recording(directory, q->file, &before)) {
        close(directory); return error_response(404, "Finalized MP4 recording not found", 0);
    }
    fd = openat(directory, q->file, O_RDONLY | O_NOFOLLOW | O_CLOEXEC | O_NONBLOCK);
    close(directory);
    if (fd < 0) return path_error();
    if (fstat(fd, &after) || !S_ISREG(after.st_mode) || after.st_nlink != 1
        || after.st_dev != before.st_dev || after.st_ino != before.st_ino
        || after.st_size != before.st_size) {
        close(fd); return error_response(503, "Recording changed; retry later", 0);
    }
    status = byte_range(getenv("HTTP_RANGE"), (uint64_t)after.st_size, &first, &last);
    if (status == 416) { close(fd); return error_response(416, "Invalid recording byte range", (uint64_t)after.st_size); }
    if (lseek(fd, (off_t)first, SEEK_SET) < 0) { close(fd); return error_response(503, "Recording seek failed", 0); }
    remaining = last - first + 1;
    printf("Status: %d %s\r\nContent-Type: video/mp4\r\nContent-Length: %" PRIu64
           "\r\nAccept-Ranges: bytes\r\nCache-Control: no-store\r\nX-Content-Type-Options: nosniff\r\n"
           "Content-Disposition: attachment; filename=\"%s\"\r\n", status, status_text(status), remaining, q->file);
    if (status == 206) printf("Content-Range: bytes %" PRIu64 "-%" PRIu64 "/%" PRIu64 "\r\n", first, last, (uint64_t)after.st_size);
    printf("\r\n");
    if (fflush(stdout)) { close(fd); return 1; }
    if (head_request) { close(fd); return 0; }
    while (remaining) {
        size_t wanted = remaining < sizeof(buffer) ? (size_t)remaining : sizeof(buffer);
        ssize_t n = read(fd, buffer, wanted);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0 || !write_all(buffer, (size_t)n)) { close(fd); return 1; }
        remaining -= (uint64_t)n;
    }
    close(fd);
    return 0;
}
int main(void) {
    const char *method = getenv("REQUEST_METHOD"), *user = getenv("REMOTE_USER");
    struct query q;
    int root, result;
    head_request = method && !strcmp(method, "HEAD");
    signal(SIGPIPE, SIG_IGN);
    /* Bound slow clients/scans without retaining resident per-request workers. */
    alarm(300);
    if (!method || (strcmp(method, "GET") && strcmp(method, "HEAD")))
        return error_response(405, "Read-only endpoint", 0);
    if (!user || !*user || strlen(user) > 32) return error_response(401, "Authentication required", 0);
    if (!parse_query(&q)) return error_response(400, "Invalid recordings query", 0);
    root = open_root(); if (root < 0) return path_error();
    if (!strcmp(q.action, "download")) result = download(root, &q);
    else if (q.seen & 2) result = list_files(root, &q);
    else result = list_days(root, &q);
    close(root);
    return result;
}
