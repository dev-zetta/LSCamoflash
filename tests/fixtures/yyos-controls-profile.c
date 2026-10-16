/* White-box ARM tests with synthetic CPU/process metadata only. */
#define open fixture_open
#define read fixture_read
#define close fixture_close
#define getuid fixture_getuid
#define geteuid fixture_geteuid
#define uname fixture_uname
#define opendir fixture_opendir
#define readdir fixture_readdir
#define closedir fixture_closedir
#define fstat fixture_fstat
#define main candidate_main
#include "../../SOURCE/src/contrib/yyos-controls/yyos_controls.c"
#undef main
static const char *cpu_text, *machine = "armv5tejl";
static uid_t uid, euid;
static int proc_index, proc_mode;
int fixture_open(const char *name, int flags, ...)
{
    (void)flags;
    if (!strcmp(name, "/proc/cpuinfo")) return 7;
    if (!strcmp(name, "/proc/446/exe") && proc_mode != 0 && proc_mode != 3)
        return 446;
    if (!strcmp(name, "/proc/777/exe") && (proc_mode == 2 || proc_mode == 3))
        return 777;
    errno = ENOENT; return -1;
}
ssize_t fixture_read(int fd, void *p, size_t n)
{
    if (fd != 7) { errno = EBADF; return -1; }
    size_t bytes = strlen(cpu_text); if (bytes > n) bytes = n;
    memcpy(p, cpu_text, bytes); return (ssize_t)bytes;
}
int fixture_close(int fd) { (void)fd; return 0; }
uid_t fixture_getuid(void) { return uid; }
uid_t fixture_geteuid(void) { return euid; }
int fixture_uname(struct utsname *out)
{
    memset(out, 0, sizeof(*out)); strcpy(out->machine, machine); return 0;
}
DIR *fixture_opendir(const char *path)
{
    if (strcmp(path, "/proc")) return NULL;
    proc_index = 0; return (DIR *)1;
}
struct dirent *fixture_readdir(DIR *directory)
{
    (void)directory; static struct dirent entry;
    const char *names[] = {".", "446", "777"};
    if (proc_index >= 3) return NULL;
    memset(&entry, 0, sizeof(entry)); strcpy(entry.d_name, names[proc_index++]);
    return &entry;
}
int fixture_closedir(DIR *directory) { (void)directory; return 0; }
int fixture_fstat(int fd, struct stat *out)
{
    if (fd != 446 && fd != 777) { errno = EBADF; return -1; }
    memset(out, 0, sizeof(*out)); out->st_mode = S_IFREG | 0555;
    out->st_dev = 10; out->st_ino = proc_mode == 4 ? 99 : 12; out->st_size = 123;
    return 0;
}
static int checks, failures;
#define CHECK(expression) do { ++checks; if (!(expression)) ++failures; } while (0)
int main(void)
{
    static const char good[] = "model name\t: ARM926EJ-S rev 5 (v5l)\nCPU architecture: 5TEJ\nHardware: AK3918AV130\n";
    cpu_text = good; CHECK(exact_cpu() == 0);
    uid = 1000; CHECK(exact_cpu() != 0); uid = 0;
    euid = 1000; CHECK(exact_cpu() != 0); euid = 0;
    machine = "armv7l"; CHECK(exact_cpu() != 0); machine = "armv5tejl";
    cpu_text = "model name: ARM926EJ-S rev 5 (v5l)\nCPU architecture: 5TEJ\nHardware: OTHER\n";
    CHECK(exact_cpu() != 0);
    cpu_text = "model name: ARM926EJ-S rev 5 (v5l)\nCPU architecture: 7\nHardware: AK3918AV130\n";
    CHECK(exact_cpu() != 0);
    cpu_text = "model name: ARM926EJ-S rev 4 (v5l)\nCPU architecture: 5TEJ\nHardware: AK3918AV130\n";
    CHECK(exact_cpu() != 0);
    cpu_text = "model name: ARM926EJ-S rev 5 (v5l)\nCPU architecture: 5TEJ\n";
    CHECK(exact_cpu() != 0);
    cpu_text = "model name: ARM926EJ-S rev 5 (v5l)\nCPU architecture: 5TEJ\nHardware: AK3918AV130\nHardware: AK3918AV130\n";
    CHECK(exact_cpu() != 0);
    struct stat verified = {.st_dev=10,.st_ino=12,.st_size=123,.st_mode=S_IFREG|0555};
    verified_stock_pid = 0; proc_mode = 0; CHECK(running_stock_matches(&verified) != 0);
    verified_stock_pid = 0; proc_mode = 1; CHECK(running_stock_matches(&verified) == 0 && verified_stock_pid == 446);
    verified_stock_pid = 0; proc_mode = 2; CHECK(running_stock_matches(&verified) != 0);
    verified_stock_pid = 0; proc_mode = 4; CHECK(running_stock_matches(&verified) != 0);
    verified_stock_pid = 0; proc_mode = 1; CHECK(running_stock_matches(&verified) == 0);
    proc_mode = 3; CHECK(running_stock_matches(&verified) != 0);
    printf("{\"ok\":%s,\"checks\":%d,\"failures\":%d,\"metadata_synthetic\":true}\n",
           failures ? "false" : "true", checks, failures);
    return failures ? 1 : 0;
}
