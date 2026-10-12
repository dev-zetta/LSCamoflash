#define _GNU_SOURCE
#include <sys/types.h>
#include <sys/stat.h>
#include <sys/statfs.h>
#include <sys/mount.h>
#include <fcntl.h>
#include <unistd.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <limits.h>

/* Native entry for stock SD hooks. Exec replaces this process before the
 * vendor station driver can run `killall hostapd`. No mounts or flash access
 * occur here; bootstrap.sh owns runtime setup after the mount is verified. */
#ifndef BOOTSTRAP_FIXTURE_ROOT
#define CARD_ROOT "/mnt"
#define MOUNTS_FILE "/proc/mounts"
#define MMC_PREFIX "/dev/mmcblk"
#else
/* Hermetic tests only: never enabled in the packaged ARM build. */
#define CARD_ROOT BOOTSTRAP_FIXTURE_ROOT "/card"
#define MOUNTS_FILE BOOTSTRAP_FIXTURE_ROOT "/mounts"
#define MMC_PREFIX BOOTSTRAP_FIXTURE_ROOT "/mmcblk"
#endif

static int open_directory(const char *path) {
    char copy[PATH_MAX], *part, *save;
    int fd, next;
    if (path[0] != '/' || strlen(path) >= sizeof(copy)) return -1;
    strcpy(copy, path);
    fd = open("/", O_RDONLY | O_DIRECTORY | O_CLOEXEC);
    if (fd < 0) return -1;
    for (part = strtok_r(copy, "/", &save); part; part = strtok_r(NULL, "/", &save)) {
        if (!strcmp(part, ".") || !strcmp(part, "..")) { close(fd); return -1; }
        next = openat(fd, part, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
        close(fd);
        if (next < 0) return -1;
        fd = next;
    }
    return fd;
}

static int mmc_source(const char *source) {
    const char *p;
    size_t length = strlen(MMC_PREFIX);
    if (strncmp(source, MMC_PREFIX, length)) return 0;
    p = source + length;
    if (*p < '0' || *p > '9') return 0;
    while (*p >= '0' && *p <= '9') p++;
    if (*p == 'p') {
        p++;
        if (*p < '0' || *p > '9') return 0;
        while (*p >= '0' && *p <= '9') p++;
    }
    return !*p;
}

static int writable(const char *options) {
    const char *p = options;
    while (*p) {
        const char *end = strchr(p, ',');
        size_t length = end ? (size_t)(end - p) : strlen(p);
        if (length == 2 && !strncmp(p, "rw", 2)) return 1;
        if (!end) break;
        p = end + 1;
    }
    return 0;
}

static int verified_card(void) {
    int fd = open_directory(CARD_ROOT), matches = 0, rw = 0;
    struct stat card, device;
    struct statfs fs;
    char line[12288], source[PATH_MAX], target[PATH_MAX], type[64], options[1024];
    FILE *mounts;
    if (fd < 0) return -1;
    if (fstat(fd, &card) || fstatfs(fd, &fs) || (fs.f_flags & MS_RDONLY)) goto bad;
#ifndef BOOTSTRAP_FIXTURE_ROOT
    if ((unsigned long)fs.f_type != 0x4d44UL) goto bad;
#endif
    mounts = fopen(MOUNTS_FILE, "r");
    if (!mounts) goto bad;
    while (fgets(line, sizeof(line), mounts)) {
        if (!strchr(line, '\n') && !feof(mounts)) { fclose(mounts); goto bad; }
        if (sscanf(line, "%4095s %4095s %63s %1023s", source, target, type, options) != 4) continue;
        if (strcmp(target, CARD_ROOT) || !mmc_source(source)) continue;
        if (strcmp(type, "vfat") && strcmp(type, "fat") && strcmp(type, "msdos")) continue;
        if (lstat(source, &device)) { fclose(mounts); goto bad; }
#ifndef BOOTSTRAP_FIXTURE_ROOT
        if (!S_ISBLK(device.st_mode) || card.st_dev != device.st_rdev) continue;
#else
        if (!S_ISREG(device.st_mode)) continue;
#endif
        matches++;
        rw = writable(options);
    }
    if (ferror(mounts)) { fclose(mounts); goto bad; }
    fclose(mounts);
    /* Ignore covered tmpfs rows, but reject ambiguous same-device stacks. */
    if (matches != 1 || !rw) goto bad;
    return fd;
bad:
    close(fd);
    return -1;
}

static int regular_file(int directory, const char *name, off_t maximum) {
    struct stat st;
    int fd = openat(directory, name, O_RDONLY | O_NOFOLLOW | O_NONBLOCK);
    if (fd < 0) return -1;
    if (fstat(fd, &st) || !S_ISREG(st.st_mode) || st.st_size <= 0 || st.st_size > maximum) {
        close(fd);
        return -1;
    }
    return fd;
}

int main(int argc, char **argv) {
    int card, busybox, script, i;
    char busybox_path[64], script_path[64];
    char **args;
    /* Stock sometimes closes descriptors before launching the hook. */
    for (i = 0; i < 3; i++) {
        if (fcntl(i, F_GETFD) < 0 && errno == EBADF) {
            int fd = open("/dev/null", O_RDWR);
            if (fd != i) return 2;
        }
    }
    if (argc > 128 || (card = verified_card()) < 0) {
        fputs("LSCamoflash: no verified writable FAT MMC mount\n", stderr);
        return 2;
    }
    busybox = regular_file(card, "busybox", 8 * 1024 * 1024);
    script = regular_file(card, "bootstrap.sh", 1024 * 1024);
    if (busybox < 0 || script < 0) {
        fputs("LSCamoflash: missing regular busybox/bootstrap.sh\n", stderr);
        return 3;
    }
    if (fcntl(busybox, F_SETFD, FD_CLOEXEC) < 0) return 4;
    snprintf(busybox_path, sizeof(busybox_path), "/proc/self/fd/%d", busybox);
    snprintf(script_path, sizeof(script_path), "/proc/self/fd/%d", script);
    args = calloc((size_t)argc + 5, sizeof(*args));
    if (!args) return 4;
    args[0] = "busybox"; args[1] = "sh"; args[2] = script_path; args[3] = CARD_ROOT;
    for (i = 1; i < argc; i++) args[i + 3] = argv[i];
    setenv("PATH", "/bin:/sbin:/usr/bin:/usr/sbin", 1);
    setenv("LC_ALL", "C", 1);
    execv(busybox_path, args);
    perror("LSCamoflash: native bootstrap exec");
    return 126;
}
