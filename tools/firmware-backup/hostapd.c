#define _GNU_SOURCE
#include <sys/types.h>
#include <sys/stat.h>
#include <sys/statfs.h>
#include <sys/mount.h>
#include <sys/wait.h>
#include <fcntl.h>
#include <unistd.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdarg.h>
#include <string.h>
#include <limits.h>
#include <poll.h>
#include <signal.h>
#include <time.h>

/* No system(), shell expansion, mount, credentials, network or MTD access. */
#define LOG_MAX_BYTES 65536
#define LOG_NAME "backup-launcher.log"
static volatile sig_atomic_t owned_child=0, cancelled=0;
static void cancel_handler(int sig) {
    int saved=errno;
    cancelled=sig;
    if (owned_child > 0) {
        if (kill(-(pid_t)owned_child,sig) < 0) kill((pid_t)owned_child,sig);
    }
    errno=saved;
}
#ifndef LAUNCHER_FIXTURE_ROOT
#define MOUNTS_FILE "/proc/mounts"
#define MMC_PREFIX "/dev/mmcblk"
static const char *roots[] = {"/mnt", "/tmp/sd", "/mnt/sdcard", NULL};
#else
/* Offline fixture binary only; production build does not contain this branch. */
#define MOUNTS_FILE LAUNCHER_FIXTURE_ROOT "/proc/mounts"
#define MMC_PREFIX LAUNCHER_FIXTURE_ROOT "/dev/mmcblk"
static const char *roots[] = {LAUNCHER_FIXTURE_ROOT "/sd", NULL};
#endif

static int reserve_stdio(void) {
    int i;
    for (i=0;i<3;i++) {
        if (fcntl(i,F_GETFD) < 0 && errno == EBADF) {
            int fd=open("/dev/null",O_RDWR|O_NOFOLLOW);
            if (fd < 0) return -1;
            if (fd != i) { if (dup2(fd,i) < 0) { close(fd); return -1; } close(fd); }
        }
    }
    return 0;
}
static int write_all(int fd, const char *buf, size_t len) {
    while (len) {
        ssize_t n = write(fd, buf, len);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) return -1;
        buf += n; len -= (size_t)n;
    }
    return 0;
}
static int log_line(int fd, const char *fmt, ...) {
    char line[1024]; struct stat st; va_list ap; int n;
    va_start(ap, fmt); n = vsnprintf(line, sizeof(line), fmt, ap); va_end(ap);
    if (n < 0 || (size_t)n >= sizeof(line)) { errno = EOVERFLOW; return -1; }
    if (fstat(fd, &st) || !S_ISREG(st.st_mode) || st.st_size < 0 ||
        st.st_size > LOG_MAX_BYTES - n) { errno = EFBIG; return -1; }
    if (write_all(fd, line, (size_t)n)) return -1;
    return fsync(fd);
}
static int drain_diagnostics(int pipe_fd, int log_fd) {
    char buffer[4096]; ssize_t n; size_t drained=0; struct stat st;
    while (drained < 1024*1024) {
        n=read(pipe_fd,buffer,sizeof(buffer));
        if (n < 0 && errno == EINTR) continue;
        if (n < 0 && (errno == EAGAIN || errno == EWOULDBLOCK)) return 0;
        if (n < 0) return -1;
        if (n == 0) return 0;
        drained+=(size_t)n;
        if (fstat(log_fd,&st)) return -1;
        if (st.st_size < LOG_MAX_BYTES-2048) {
            off_t room=LOG_MAX_BYTES-2048-st.st_size;
            size_t take=(off_t)n > room ? (size_t)room : (size_t)n;
            if (write_all(log_fd,buffer,take)) return -1;
        }
    }
    return 0;
}
static int rw_option(const char *opts) {
    const char *p = opts;
    while (*p) {
        const char *end = strchr(p, ','); size_t n = end ? (size_t)(end-p) : strlen(p);
        if (n == 2 && p[0] == 'r' && p[1] == 'w') return 1;
        if (!end) break;
        p = end + 1;
    }
    return 0;
}
static int mmc_source(const char *s) {
    size_t n = strlen(MMC_PREFIX); const char *p;
    if (strncmp(s, MMC_PREFIX, n)) return 0;
    p = s+n;
    if (*p < '0' || *p > '9') return 0;
    while (*p >= '0' && *p <= '9') p++;
    if (*p == 'p') {
        p++; if (*p < '0' || *p > '9') return 0;
        while (*p >= '0' && *p <= '9') p++;
    }
    return *p == '\0';
}
static int open_dir_no_symlinks(const char *path) {
    char copy[PATH_MAX], *p, *save; int fd, next;
    if (path[0] != '/' || strlen(path) >= sizeof(copy)) { errno = EINVAL; return -1; }
    strcpy(copy, path); fd = open("/", O_RDONLY|O_DIRECTORY|O_CLOEXEC);
    if (fd < 0) return -1;
    for (p = strtok_r(copy, "/", &save); p; p = strtok_r(NULL, "/", &save)) {
        if (!strcmp(p,".") || !strcmp(p,"..")) { close(fd); errno=EINVAL; return -1; }
        next = openat(fd,p,O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);
        if (next < 0) { int e=errno; close(fd); errno=e; return -1; }
        close(fd); fd=next;
    }
    return fd;
}
static int verified_mount(const char *root, char *source, size_t source_len) {
    char line[12288], src[PATH_MAX], dest[PATH_MAX], type[64], opts[1024];
    struct stat sd_st, src_st; struct statfs fs;
    FILE *f; int fd, matches=0, selected_rw=0;
    /* Stock may overlay an SD mount on tmpfs at the same /mnt path.
       Inspect the visible filesystem first; covered entries are not outputs. */
    fd=open_dir_no_symlinks(root); if (fd < 0) return -1;
    if (fstat(fd,&sd_st) || fstatfs(fd,&fs)) goto bad;
#ifndef LAUNCHER_FIXTURE_ROOT
    if ((unsigned long)fs.f_type != 0x4d44UL || (fs.f_flags & MS_RDONLY)) { errno=EPERM; goto bad; }
#else
    if (fs.f_flags & MS_RDONLY) { errno=EPERM; goto bad; }
#endif
    f = fopen(MOUNTS_FILE,"r"); if (!f) goto bad;
    while (fgets(line,sizeof(line),f)) {
        if (!strchr(line,'\n') && !feof(f)) { fclose(f); errno=EOVERFLOW; goto bad; }
        if (sscanf(line,"%4095s %4095s %63s %1023s",src,dest,type,opts) != 4) continue;
        if (strcmp(dest,root)) continue;
        if (!mmc_source(src) || (strcmp(type,"vfat") && strcmp(type,"fat") && strcmp(type,"msdos"))) continue;
        if (lstat(src,&src_st)) { fclose(f); goto bad; }
#ifndef LAUNCHER_FIXTURE_ROOT
        if (!S_ISBLK(src_st.st_mode) || sd_st.st_dev != src_st.st_rdev) continue;
#else
        if (!S_ISREG(src_st.st_mode)) continue;
#endif
        if (strlen(src) >= source_len) { fclose(f); errno=ENAMETOOLONG; goto bad; }
        strcpy(source,src); matches++; selected_rw=rw_option(opts);
    }
    if (ferror(f)) { fclose(f); errno=EIO; goto bad; }
    fclose(f);
    /* Count RO entries too: an ambiguous same-device stack must fail closed. */
    if (matches != 1 || !selected_rw) { errno=ENODEV; goto bad; }
    return fd;
bad: { int e=errno; close(fd); errno=e; return -1; }
}
static int regular_input(int root_fd, const char *name, off_t maximum) {
    struct stat st; int fd=openat(root_fd,name,O_RDONLY|O_NOFOLLOW|O_NONBLOCK);
    if (fd < 0) return -1;
    if (fstat(fd,&st) || !S_ISREG(st.st_mode) || st.st_size <= 0 || st.st_size > maximum) {
        int e=errno ? errno : EINVAL; close(fd); errno=e; return -1;
    }
    return fd;
}

int main(int argc, char **argv) {
    const char *root=NULL; char source[PATH_MAX], bb_fd_path[64], dump_fd_path[64];
    int i, root_fd=-1, log_fd, bb_fd, dump_fd, status, e, output_pipe[2]; pid_t child, got;
    struct sigaction action; sigset_t unblock;
    struct stat st;
    (void)argv; /* Stock hostapd arguments are deliberately ignored. */
    if (reserve_stdio()) return 2;
    for (i=0; roots[i]; i++) {
        root_fd=verified_mount(roots[i],source,sizeof(source));
        if (root_fd >= 0) { root=roots[i]; break; }
    }
    if (root_fd < 0) {
        fprintf(stderr,"backup native launcher: no verified RW FAT MMC mount; no files written\n");
        return 2;
    }
    log_fd=openat(root_fd,LOG_NAME,O_WRONLY|O_CREAT|O_APPEND|O_NOFOLLOW|O_NONBLOCK|O_CLOEXEC,0600);
    if (log_fd < 0 || fstat(log_fd,&st) || !S_ISREG(st.st_mode) || st.st_size < 0 || st.st_size > LOG_MAX_BYTES) {
        fprintf(stderr,"backup native launcher: refusing diagnostic log\n");
        if (log_fd >= 0) close(log_fd);
        close(root_fd); return 3;
    }
    if (log_line(log_fd,"NATIVE_ENTRY version=2 pid=%ld uid=%ld argc=%d root=%s source=%s\n",
        (long)getpid(),(long)getuid(),argc,root,source)) { close(log_fd); close(root_fd); return 3; }
    bb_fd=regular_input(root_fd,"busybox",8*1024*1024);
    if (bb_fd < 0) { e=errno; log_line(log_fd,"BUSYBOX_OPEN_ERROR errno=%d\n",e); close(log_fd); close(root_fd); return 4; }
    dump_fd=regular_input(root_fd,"dump.sh",1024*1024);
    if (dump_fd < 0) { e=errno; log_line(log_fd,"DUMPER_OPEN_ERROR errno=%d\n",e); close(bb_fd); close(log_fd); close(root_fd); return 4; }
    snprintf(bb_fd_path,sizeof(bb_fd_path),"/proc/self/fd/%d",bb_fd);
    snprintf(dump_fd_path,sizeof(dump_fd_path),"/proc/self/fd/%d",dump_fd);
    if (log_line(log_fd,"EXEC_START busybox=verified-open-fd dumper=verified-open-fd\n")) {
        close(dump_fd); close(bb_fd); close(log_fd); close(root_fd); return 3;
    }
    if (pipe(output_pipe) || fcntl(output_pipe[0],F_SETFL,O_NONBLOCK) < 0) {
        e=errno; log_line(log_fd,"PIPE_ERROR errno=%d\n",e); status=5; goto done;
    }
    memset(&action,0,sizeof(action)); action.sa_handler=cancel_handler;
    sigemptyset(&action.sa_mask);
    sigaction(SIGTERM,&action,NULL); sigaction(SIGHUP,&action,NULL); sigaction(SIGINT,&action,NULL);
    signal(SIGCHLD,SIG_DFL); /* Inherited SIG_IGN must not auto-reap our child. */
    sigemptyset(&unblock); sigaddset(&unblock,SIGTERM); sigaddset(&unblock,SIGHUP);
    sigaddset(&unblock,SIGINT); sigaddset(&unblock,SIGCHLD);
    sigprocmask(SIG_UNBLOCK,&unblock,NULL);
    child=fork();
    if (child < 0) { e=errno; log_line(log_fd,"FORK_ERROR errno=%d\n",e); close(output_pipe[0]); close(output_pipe[1]); status=5; goto done; }
    if (child == 0) {
        char *child_argv[]={"busybox","sh",dump_fd_path,(char *)root,NULL};
        char *child_env[]={"PATH=/bin:/sbin:/usr/bin:/usr/sbin","LC_ALL=C",NULL};
        signal(SIGTERM,SIG_DFL); signal(SIGHUP,SIG_DFL); signal(SIGINT,SIG_DFL);
        if (setpgid(0,0) < 0) { e=errno; log_line(log_fd,"CHILD_GROUP_ERROR errno=%d\n",e); _exit(126); }
        close(output_pipe[0]);
        if (dup2(output_pipe[1],STDOUT_FILENO) < 0 || dup2(output_pipe[1],STDERR_FILENO) < 0) {
            e=errno; log_line(log_fd,"DUP_ERROR errno=%d\n",e); _exit(126);
        }
        close(output_pipe[1]);
        execve(bb_fd_path,child_argv,child_env);
        e=errno; log_line(log_fd,"EXEC_ERROR errno=%d\n",e); _exit(126);
    }
    owned_child=child;
    setpgid(child,child); /* Child also sets its own group before exec. */
    close(output_pipe[1]);
    if (cancelled) cancel_handler(cancelled);
    /* Drain child diagnostics with a hard byte cap; never cap backup files. */
    for (;;) {
        struct pollfd poll_fd;
        if (drain_diagnostics(output_pipe[0],log_fd)) cancel_handler(SIGTERM);
        do { got=waitpid(child,&status,WNOHANG); } while (got < 0 && errno == EINTR);
        if (got == child || got < 0) break;
        poll_fd.fd=output_pipe[0]; poll_fd.events=POLLIN|POLLHUP; poll_fd.revents=0;
        if (poll(&poll_fd,1,100) < 0 && errno != EINTR) cancel_handler(SIGTERM);
        if ((poll_fd.revents & POLLHUP) && !(poll_fd.revents & POLLIN)) {
            struct timespec pause_time={0,100000000}; nanosleep(&pause_time,NULL);
        }
    }
    /* Reaping makes the child's final bytes stable; drain the exit race too. */
    if (drain_diagnostics(output_pipe[0],log_fd)) log_line(log_fd,"OUTPUT_READ_ERROR\n");
    close(output_pipe[0]); owned_child=0;
    if (cancelled) log_line(log_fd,"CANCELLED signal=%d child-reaped=yes\n",cancelled);
    if (got < 0) { e=errno; log_line(log_fd,"WAIT_ERROR errno=%d\n",e); status=5; }
    else if (WIFEXITED(status)) { status=WEXITSTATUS(status); log_line(log_fd,"CHILD_EXIT code=%d\n",status); }
    else if (WIFSIGNALED(status)) { int sig=WTERMSIG(status); status=128+sig; log_line(log_fd,"CHILD_SIGNAL signal=%d exit=%d\n",sig,status); }
    else { status=5; log_line(log_fd,"CHILD_UNKNOWN_STATUS\n"); }
done:
    close(dump_fd); close(bb_fd); close(log_fd); close(root_fd); return status;
}
