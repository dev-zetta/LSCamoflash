#!/bin/sh
# Read-only NOR MTD collection. All outputs stay on the supplied SD mount.
# Invoke with the kit's static BusyBox: busybox sh dump.sh /mnt
# No flash writes, mounts, service changes, concatenation, or network operations.
set -eu
umask 077
PROC=/proc
SYS=/sys
DEV=/dev
FS_ROOT=/
MAX_SINGLE_BYTES=67108864
MAX_TOTAL_BYTES=134217728
MAX_PARTITIONS=64
MAX_FILESYSTEM_KIB=131072
MAX_ATTEMPTS=3
MAX_RUN_NAMES=64
TOTAL_BUDGET_SECONDS=240
MAX_COMMAND_SECONDS=20
SD_ROOT=${1-}
[ "$#" -eq 1 ] && [ -n "$SD_ROOT" ] || { printf '%s\n' 'usage: dump.sh SD_MOUNT_ROOT' >&2; exit 2; }
case "$SD_ROOT" in /*) ;; *) printf '%s\n' 'SD root must be absolute' >&2; exit 2;; esac
case "$SD_ROOT" in *' '*|*'\'*|*'	'*|*'
'*) printf '%s\n' 'SD root contains unsupported whitespace/escape' >&2; exit 2;; esac
SD_ROOT=$(cd "$SD_ROOT" && pwd -P)
[ "$SD_ROOT" != / ] || { printf '%s\n' 'Refusing root filesystem output' >&2; exit 2; }
BB=${BACKUP_BUSYBOX:-$SD_ROOT/busybox}
[ -f "$BB" ] && [ -x "$BB" ] || { printf '%s\n' 'Missing executable kit BusyBox' >&2; exit 2; }
# Bound each operation directly, so its writer/reader remains foreground.
# Kernel uninterruptible I/O cannot be bounded by a userspace timeout.
read -r started_uptime uptime_rest < "$PROC/uptime"
START_SECONDS=${started_uptime%%.*}
DEADLINE=$((START_SECONDS + TOTAL_BUDGET_SECONDS))
"$BB" timeout -k 1 1 "$BB" true || { printf '%s\n' 'Missing BusyBox timeout applet' >&2; exit 2; }
tool() {
    read -r current_uptime uptime_rest < "$PROC/uptime"
    remaining=$((DEADLINE - ${current_uptime%%.*}))
    [ "$remaining" -gt 0 ] || { printf '%s\n' 'Overall backup time budget exhausted' >&2; return 124; }
    command_seconds=$MAX_COMMAND_SECONDS
    case "$1" in dd) command_seconds=30;; tar) command_seconds=45;; sync) command_seconds=15;; esac
    [ "$command_seconds" -le "$remaining" ] || command_seconds=$remaining
    "$BB" timeout -s TERM -k 2 "$command_seconds" "$BB" "$@"
}
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
is_uint() { case "$1" in ''|*[!0-9]*) return 1;; *) return 0;; esac; }
[ "$(tool id -u)" = 0 ] || die 'Root access is required'
# Prove the visible filesystem first: stock firmware can leave a covered tmpfs
# entry at /mnt when it overlays the SD card, and /proc/mounts lists both.
visible_fs=$(tool stat -f -c '%t' "$SD_ROOT") || die 'Cannot inspect output filesystem'
[ "$visible_fs" = 4d44 ] || die 'Visible output filesystem is not FAT'
visible_dev=$(tool stat -c '%d' "$SD_ROOT") || die 'Cannot inspect output device'
is_uint "$visible_dev" || die 'Invalid visible output device'
visible_major=$(((visible_dev >> 8) & 0xfff))
visible_minor=$(((visible_dev & 0xff) | ((visible_dev >> 12) & 0xfff00)))
# Match only the MMC/FAT mount whose block identity is visible through SD_ROOT.
# Count matching read-only rows too, so a covered RW row cannot bless a RO top.
mount_found=0
mount_rw_found=0
while read -r mount_source mount_path mount_fs mount_opts mount_rest; do
    [ "$mount_path" = "$SD_ROOT" ] || continue
    case "$mount_source" in "$DEV"/mmcblk[0-9]*) ;; *) continue;; esac
    case "$mount_fs" in vfat|fat|msdos) ;; *) continue;; esac
    [ -b "$mount_source" ] || continue # FIXTURE_BLOCK_CHECK
    source_dev=$(tool stat -c '%t:%T' "$mount_source") || die 'Cannot inspect SD block device'
    case "$source_dev" in *:*) source_major=${source_dev%:*}; source_minor=${source_dev#*:};; *) die 'Invalid SD device numbers';; esac
    case "$source_major" in ''|*[!0-9a-fA-F]*) die 'Invalid SD device major';; esac
    case "$source_minor" in ''|*[!0-9a-fA-F]*) die 'Invalid SD device minor';; esac
    [ "$((0x$source_major))" -eq "$visible_major" ] && [ "$((0x$source_minor))" -eq "$visible_minor" ] || continue
    mount_found=$((mount_found + 1))
    case ",$mount_opts," in *,rw,*) mount_rw_found=$((mount_rw_found + 1));; esac
done < "$PROC/mounts"
[ "$mount_found" -eq 1 ] && [ "$mount_rw_found" -eq 1 ] || die 'SD root is not one verified read/write mountpoint'
# Refuse existing symlinks; retain a unique run directory and all failed evidence.
BASE=$SD_ROOT/firmware-backup
LOCK=$SD_ROOT/.firmware-backup.lock
[ ! -L "$BASE" ] && [ ! -L "$LOCK" ] || die 'Output or lock is a symlink'
tool mkdir "$LOCK" || die 'A backup is already running or a stale lock exists'
OUT=
COMPLETE=0
cleanup() {
    status=$?
    trap - 0 HUP INT TERM
    if [ "$COMPLETE" -ne 1 ] && [ -n "$OUT" ] && [ -d "$OUT" ]; then
        printf 'FAILED exit=%s\n' "$status" > "$OUT/status.part" || :
        "$BB" timeout -k 1 3 "$BB" mv "$OUT/status.part" "$OUT/status.txt" || :
        "$BB" timeout -k 1 3 "$BB" sync -f "$OUT" || :
    fi
    "$BB" timeout -k 1 3 "$BB" rmdir "$LOCK" || :
    exit "$status"
}
trap cleanup 0
trap 'exit 130' INT
trap 'exit 143' HUP TERM
[ ! -e "$BASE" ] || [ -d "$BASE" ] || die 'Output base is not a directory'
tool mkdir -p "$BASE"
# The camera clock and PID can repeat across boots. Claim a new directory
# atomically, and never let cleanup write into an older verified run.
run_prefix=$BASE/run-$(tool date -u +%Y%m%dT%H%M%SZ)-$$
run_number=0
while [ "$run_number" -lt "$MAX_RUN_NAMES" ]; do
    candidate=$run_prefix
    [ "$run_number" -eq 0 ] || candidate=$run_prefix-$run_number
    if tool mkdir "$candidate" 2>/dev/null; then
        OUT=$candidate
        break
    fi
    [ -e "$candidate" ] || [ -L "$candidate" ] || die 'Cannot create backup run directory'
    run_number=$((run_number + 1))
done
[ -n "$OUT" ] || die 'No unused backup run directory within bounded attempts'
printf 'Backup output: %s\n' "$OUT"
exec > "$OUT/run.log" 2>&1
printf 'IN_PROGRESS\n' > "$OUT/status.txt"
tool mkdir "$OUT/meta" "$OUT/partitions" "$OUT/attempts"
# This kit intentionally uses its own BusyBox applets, avoiding unknown PATH tools.
tool --help > "$OUT/meta/busybox-help.txt" 2>&1
tool sha256sum </dev/null > "$OUT/meta/sha256-empty.txt"
read -r empty_hash empty_rest < "$OUT/meta/sha256-empty.txt"
[ "$empty_hash" = e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855 ] || die 'SHA256 applet failed its known-answer check'
tool sync -f "$OUT" || die 'BusyBox/filesystem cannot sync the SD filesystem'
bytes() {
    byte_output=$(tool wc -c < "$1") || return 1
    # Shell word splitting strips wc padding without a pipeline hiding failure.
    set -- $byte_output
    [ "$#" -eq 1 ] && is_uint "$1" || return 1
    printf '%s\n' "$1"
}
hash() {
    hash_line=$(tool sha256sum "$1") || return 1
    printf '%s\n' "${hash_line%% *}"
}
# Metadata only: no credential values are printed to the console.
for item in mtd mounts cmdline cpuinfo version meminfo; do
    [ ! -r "$PROC/$item" ] || tool cat "$PROC/$item" > "$OUT/meta/proc-$item.txt"
done
tool uname -a > "$OUT/meta/uname.txt"
tool dmesg > "$OUT/meta/dmesg-before.txt" 2>&1 || :
for pid_path in "$PROC"/[0-9]*; do
    [ -r "$pid_path/comm" ] || continue
    comm=$(tool cat "$pid_path/comm")
    [ "$comm" = anyka_ipc ] || continue
    pid=${pid_path##*/}
    [ ! -r "$pid_path/maps" ] || tool cat "$pid_path/maps" > "$OUT/meta/anyka_ipc-$pid-maps.txt"
    tool readlink "$pid_path/exe" > "$OUT/meta/anyka_ipc-$pid-exe.txt" 2>&1 || :
done
# Capture the complete standard userspace trees together; tar preserves symlinks.
# The raw APP/rootfs MTD images remain the authoritative matching binary/library set.
set --
for tree in bin sbin lib lib32 lib64 usr etc opt; do
    [ ! -e "$FS_ROOT/$tree" ] && [ ! -L "$FS_ROOT/$tree" ] || set -- "$@" "$tree"
done
[ "$#" -gt 0 ] || die 'No stock userspace trees found'
: > "$OUT/meta/userspace-du.txt"
for tree in "$@"; do tool du -sk "$FS_ROOT/$tree" >> "$OUT/meta/userspace-du.txt" 2>&1; done
filesystem_kib=0
while read -r tree_kib tree_path; do
    is_uint "$tree_kib" || die 'Cannot measure userspace size'
    filesystem_kib=$((filesystem_kib + tree_kib))
done < "$OUT/meta/userspace-du.txt"
[ "$filesystem_kib" -le "$MAX_FILESYSTEM_KIB" ] || die 'Userspace exceeds archive cap'
tool df -Pk "$SD_ROOT" > "$OUT/meta/df-userspace.txt"
available_kib=$(tool awk 'NR > 1 {v=$4} END {print v}' "$OUT/meta/df-userspace.txt")
is_uint "$available_kib" || die 'Cannot determine SD free space'
[ "$available_kib" -ge "$((filesystem_kib + 4096))" ] || die 'Insufficient SD space for userspace snapshot'
: > "$OUT/SHA256SUMS"
# Store source trees as a separate filesystem snapshot; do not execute archived code.
tool tar -cf "$OUT/stock-userspace.tar.part" -C "$FS_ROOT" "$@" 2> "$OUT/userspace-tar.log" || die 'Userspace archive failed or files changed during capture'
tool tar -tf "$OUT/stock-userspace.tar.part" > "$OUT/meta/userspace-members.txt" || die 'Userspace archive unreadable'
tool mv "$OUT/stock-userspace.tar.part" "$OUT/stock-userspace.tar"
printf '%s  stock-userspace.tar\n' "$(hash "$OUT/stock-userspace.tar")" >> "$OUT/SHA256SUMS"
bytes "$OUT/stock-userspace.tar" > "$OUT/meta/stock-userspace-bytes.txt"
[ -r "$OUT/meta/proc-mtd.txt" ] || die 'Missing /proc/mtd'
printf 'id\tbytes\terase_bytes\ttype\twrite_bytes\toob_bytes\toffset\tdev\tname\n' > "$OUT/partitions.tsv"
count=0
total=0
seen=' '
while read -r mtd_id size_hex erase_hex proc_name; do
    case "$mtd_id" in mtd*:)
        mtd_id=${mtd_id%:}; number=${mtd_id#mtd}
        is_uint "$number" || die 'Invalid /proc/mtd numeric ID'
        case "$seen" in *" $mtd_id "*) die 'Duplicate MTD ID';; esac
        seen="$seen$mtd_id "
        case "$size_hex$erase_hex" in ''|*[!0-9a-fA-F]*) die 'Invalid MTD hexadecimal geometry';; esac
        size=$((0x$size_hex)); erase=$((0x$erase_hex))
        [ "$size" -gt 0 ] && [ "$size" -le "$MAX_SINGLE_BYTES" ] || die "$mtd_id size outside backup cap"
        [ "$erase" -gt 0 ] && [ "$erase" -le "$size" ] || die "$mtd_id invalid erase geometry"
        sys=$SYS/class/mtd/$mtd_id
        [ -d "$sys" ] || die "$mtd_id missing sysfs metadata"
        tool mkdir "$OUT/meta/$mtd_id"
        for attr in name type size erasesize writesize oobsize offset dev flags ecc_failures corrected_bits bad_blocks bbt_blocks; do
            [ ! -r "$sys/$attr" ] || tool cat "$sys/$attr" > "$OUT/meta/$mtd_id/$attr"
        done
        for attr in type size erasesize writesize oobsize dev name; do
            [ -s "$OUT/meta/$mtd_id/$attr" ] || die "$mtd_id missing $attr"
        done
        type=$(tool cat "$sys/type"); sys_size=$(tool cat "$sys/size"); sys_erase=$(tool cat "$sys/erasesize")
        write=$(tool cat "$sys/writesize"); oob=$(tool cat "$sys/oobsize"); devnum=$(tool cat "$sys/dev")
        name=$(tool cat "$sys/name" | tool tr '\t\r\n' '   ')
        [ "$type" = nor ] || die "$mtd_id is $type: NAND/unknown requires a separate ECC/OOB-aware plan"
        is_uint "$sys_size" && is_uint "$sys_erase" && is_uint "$write" && is_uint "$oob" || die "$mtd_id invalid sysfs geometry"
        [ "$sys_size" -eq "$size" ] && [ "$sys_erase" -eq "$erase" ] || die "$mtd_id /proc and sysfs sizes disagree"
        # Restrict this reader to byte-write NOR and the observed EV330 write unit.
        # writesize describes writes; it does not change the byte-for-byte read plan.
        case "$write" in 1|256) ;; *) die "$mtd_id unsupported NOR write unit";; esac
        [ "$oob" -eq 0 ] || die "$mtd_id inconsistent NOR write/OOB geometry"
        [ "$((erase % write))" -eq 0 ] && [ "$((size % erase))" -eq 0 ] &&
            [ "$((size % write))" -eq 0 ] || die "$mtd_id unaligned NOR geometry"
        dev=$DEV/$mtd_id
        [ -c "$dev" ] && [ -r "$dev" ] || die "$mtd_id is not a readable MTD character device" # FIXTURE_CHAR_CHECK
        case "$devnum" in *:*) major=${devnum%:*}; minor=${devnum#*:};; *) die "$mtd_id invalid device numbers";; esac
        is_uint "$major" && is_uint "$minor" || die "$mtd_id invalid device numbers"
        actual=$(tool stat -c '%t:%T' "$dev")
        actual_major=${actual%:*}; actual_minor=${actual#*:}
        [ "$((0x$actual_major))" -eq "$major" ] && [ "$((0x$actual_minor))" -eq "$minor" ] || die "$mtd_id character device/sysfs mismatch" # FIXTURE_DEVNUM_CHECK
        offset=unknown
        if [ -r "$sys/offset" ]; then offset=$(tool cat "$sys/offset"); is_uint "$offset" || die "$mtd_id invalid offset"; fi
        count=$((count + 1)); total=$((total + size))
        [ "$count" -le "$MAX_PARTITIONS" ] && [ "$total" -le "$MAX_TOTAL_BYTES" ] || die 'MTD inventory exceeds backup caps'
        printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$mtd_id" "$size" "$erase" "$type" "$write" "$oob" "$offset" "$devnum" "$name" >> "$OUT/partitions.tsv"
        ;;
    esac
done < "$OUT/meta/proc-mtd.txt"
[ "$count" -gt 0 ] || die 'No MTD partitions discovered'
# Cross-check every numeric sysfs MTD node, ignoring mtd0ro and other aliases.
sys_count=0
for sys in "$SYS"/class/mtd/mtd*; do
    mtd_id=${sys##*/}; number=${mtd_id#mtd}
    is_uint "$number" || continue
    case "$seen" in *" $mtd_id "*) ;; *) die "Sysfs $mtd_id absent from /proc/mtd";; esac
    sys_count=$((sys_count + 1))
done
[ "$sys_count" -eq "$count" ] || die 'MTD inventories disagree'
tool df -Pk "$SD_ROOT" > "$OUT/meta/df-before.txt"
available_kib=$(tool awk 'NR > 1 {v=$4} END {print v}' "$OUT/meta/df-before.txt")
is_uint "$available_kib" || die 'Cannot determine SD free space'
# Three complete two-read attempts can be retained, plus userspace and overhead.
required_kib=$(((total * 2 * MAX_ATTEMPTS + 1023) / 1024 + filesystem_kib + 4096))
[ "$available_kib" -ge "$required_kib" ] || die 'Insufficient SD free space for bounded retries'
printf 'id\tattempt\tread\tdd_exit\tbytes\tsha256\tresult\n' > "$OUT/read-attempts.tsv"
tab=$(printf '\t')
while IFS="$tab" read -r mtd_id size erase type write oob offset devnum name; do
    [ "$mtd_id" != id ] || continue
    dev=$DEV/$mtd_id
    tool mkdir "$OUT/partitions/$mtd_id" "$OUT/attempts/$mtd_id"
    attempt=1
    verified=0
    while [ "$attempt" -le "$MAX_ATTEMPTS" ]; do
        tool cmp -s "$OUT/meta/proc-mtd.txt" "$PROC/mtd" || die 'MTD layout changed during backup'
        for attr in type size erasesize writesize oobsize dev; do
            tool cmp -s "$OUT/meta/$mtd_id/$attr" "$SYS/class/mtd/$mtd_id/$attr" || die "$mtd_id metadata changed"
        done
        attempt_dir=$OUT/attempts/$mtd_id/attempt-$attempt
        tool mkdir "$attempt_dir"
        pair_ok=1
        for read_number in 1 2; do
            part=$attempt_dir/read$read_number.part
            dd_exit=0
            # No conv=noerror/sync: read errors and short output must never be hidden.
            tool dd if="$dev" of="$part" bs=4096 count=$(((size + 4095) / 4096)) 2> "$attempt_dir/read$read_number.log" || dd_exit=$?
            actual_size=$(bytes "$part") || die 'Cannot count SD output bytes'
            is_uint "$actual_size" || die 'Invalid SD output byte count'
            digest=$(hash "$part") || die 'Cannot hash SD output'
            result=ok
            if [ "$dd_exit" -ne 0 ] || [ "$actual_size" -ne "$size" ]; then result=read-error-or-size; pair_ok=0; fi
            printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$mtd_id" "$attempt" "$read_number" "$dd_exit" "$actual_size" "$digest" "$result" >> "$OUT/read-attempts.tsv"
            if [ "$read_number" -eq 1 ]; then first_hash=$digest; else second_hash=$digest; fi
        done
        if [ "$pair_ok" -eq 1 ] && [ "$first_hash" = "$second_hash" ]; then
            tool cmp -s "$attempt_dir/read1.part" "$attempt_dir/read2.part" || die 'Equal hashes but different bytes'
            for read_number in 1 2; do
                final=partitions/$mtd_id/read$read_number.bin
                tool mv "$attempt_dir/read$read_number.part" "$OUT/$final"
                printf '%s  %s\n' "$first_hash" "$final" >> "$OUT/SHA256SUMS"
            done
            verified=1
            break
        fi
        printf '%s attempt %s unstable or failed; retaining both files\n' "$mtd_id" "$attempt"
        attempt=$((attempt + 1))
    done
    [ "$verified" -eq 1 ] || die "$mtd_id has no matching complete read pair after bounded retries"
done < "$OUT/partitions.tsv"
for file in partitions.tsv read-attempts.tsv; do printf '%s  %s\n' "$(hash "$OUT/$file")" "$file" >> "$OUT/SHA256SUMS"; done
tool cmp -s "$OUT/meta/proc-mtd.txt" "$PROC/mtd" || die 'MTD layout changed during backup'
tool dmesg > "$OUT/meta/dmesg-after.txt" 2>&1 || :
tool find "$OUT/meta" -type f > "$OUT/meta-files.list"
while IFS= read -r meta_file; do
    relative=${meta_file#"$OUT/"}
    printf '%s  %s\n' "$(hash "$meta_file")" "$relative" >> "$OUT/SHA256SUMS"
done < "$OUT/meta-files.list"
tool sync -f "$OUT" || die 'SD filesystem sync failed'
(cd "$OUT" && tool sha256sum -c SHA256SUMS) > "$OUT/verification.log" 2>&1 || die 'SD file hash verification failed'
printf 'VERIFIED_NOR_BACKUP\npartitions=%s\ntotal_partition_bytes=%s\nflash_image_concatenated=no\n' "$count" "$total" > "$OUT/status.part"
tool mv "$OUT/status.part" "$OUT/status.txt"
tool sync -f "$OUT" || die 'Final SD filesystem sync failed'
COMPLETE=1
printf '%s\n' 'Verified every discovered NOR partition with two matching complete reads.'
