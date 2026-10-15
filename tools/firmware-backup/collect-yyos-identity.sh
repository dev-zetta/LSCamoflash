#!/bin/sh
# Identity-only YYOS observations; invoke with the kit's static BusyBox.
# No MTD-device reads, daemon, network, configuration changes or boot handoff.
set -eu
umask 077
PROC=/proc
SYS=/sys
DEV=/dev
FS_ROOT=/
STOCK_ROOT=${FS_ROOT%/}
SD_PARENT=/mnt
SD_MOUNT=/mnt/sdcard
TOTAL_BUDGET_SECONDS=60
MAX_COMMAND_SECONDS=3
MAX_RUN_NAMES=16
MAX_MTD_NODES=16
MAX_PROCESS_SCAN=128
MAX_PROCESSES=4
MAX_FILE_BYTES=131072
MAX_MAP_BYTES=262144

die() { printf '%s\n' "$1" >&2; exit 1; }
uint() { case "$1" in ''|*[!0-9]*) return 1;; *) return 0;; esac; }
[ "$#" -eq 1 ] && [ "$1" = "$SD_MOUNT" ] || die 'Expected the verified /mnt/sdcard mountpoint'
for directory in "$SD_PARENT" "$SD_MOUNT"; do
    [ -d "$directory" ] && [ ! -L "$directory" ] || die 'SD path is not a plain directory'
done
BB=$SD_MOUNT/busybox
[ -f "$BB" ] && [ ! -L "$BB" ] && [ -x "$BB" ] || die 'Missing regular kit BusyBox'
read -r started_uptime ignored < "$PROC/uptime"
START_SECONDS=${started_uptime%%.*}
uint "$START_SECONDS" || die 'Invalid monotonic clock'
# Reserve ten seconds for timeout kill grace and bounded failure cleanup.
DEADLINE=$((START_SECONDS + TOTAL_BUDGET_SECONDS - 10))
"$BB" timeout -k 1 1 "$BB" true || die 'Missing BusyBox timeout support'
budget() {
    read -r current_uptime ignored < "$PROC/uptime"
    remaining=$((DEADLINE - ${current_uptime%%.*}))
    [ "$remaining" -gt 0 ] || { printf '%s\n' 'Identity time budget exhausted' >&2; exit 124; }
}
tool() {
    budget
    seconds=$MAX_COMMAND_SECONDS
    case "$1" in sha256sum|sync) seconds=5;; esac
    [ "$seconds" -le "$remaining" ] || seconds=$remaining
    "$BB" timeout -s TERM -k 1 "$seconds" "$BB" "$@"
}
[ "$(tool id -u)" = 0 ] || die 'Root access is required'
magic=$(tool stat -f -c %t "$SD_MOUNT") || die 'Cannot inspect visible SD filesystem'
[ "$magic" = 4d44 ] || die 'Visible SD filesystem is not FAT'
visible=$(tool stat -c %d "$SD_MOUNT") || die 'Cannot inspect visible SD device'
uint "$visible" || die 'Invalid visible SD device'
visible_major=$(((visible >> 8) & 4095))
visible_minor=$(((visible & 255) | ((visible >> 12) & 1048320)))
matches=0
writable=0
while read -r source destination filesystem options rest; do
    [ "$destination" = "$SD_MOUNT" ] || continue
    case "$filesystem" in vfat|fat|msdos) ;; *) continue;; esac
    case "$source" in "$DEV"/mmcblk[0-9]*) ;; *) continue;; esac
    [ -b "$source" ] && [ ! -L "$source" ] || continue # FIXTURE_BLOCK_CHECK
    pair=$(tool stat -c %t:%T "$source") || die 'Cannot inspect SD block identity'
    case "$pair" in ''|*[!0-9a-fA-F:]*|*:*:*) die 'Invalid SD block identity';; esac
    major=${pair%%:*}; minor=${pair#*:}
    [ -n "$major" ] && [ -n "$minor" ] && [ "$major" != "$pair" ] || die 'Invalid SD block identity'
    [ "$((0x$major))" -eq "$visible_major" ] && [ "$((0x$minor))" -eq "$visible_minor" ] || continue
    matches=$((matches + 1))
    case ",$options," in *,rw,*) writable=$((writable + 1));; esac
done < "$PROC/mounts"
[ "$matches" -eq 1 ] && [ "$writable" -eq 1 ] || die 'SD is not one verified writable MMC/FAT mount'

BASE=$SD_MOUNT/yyos-identity
LOCK=$SD_MOUNT/.yyos-identity.lock
[ ! -L "$BASE" ] && [ ! -L "$LOCK" ] || die 'Output or lock is a symlink'
[ ! -e "$BASE" ] || [ -d "$BASE" ] || die 'Output base is not a directory'
tool mkdir "$LOCK" || die 'Identity capture is already running or has a stale lock'
OUT=
COMPLETE=0
LOCK_OWNED=1
cleanup() {
    result=$?
    trap - 0 HUP INT TERM
    if [ "$COMPLETE" -ne 1 ] && [ -n "$OUT" ]; then
        printf 'FAILED\nexit_code=%s\n' "$result" > "$OUT/status.txt" || :
        "$BB" timeout -k 1 1 "$BB" sync "$OUT/status.txt" || :
        "$BB" timeout -k 1 1 "$BB" sync "$OUT" || :
    fi
    if [ "$LOCK_OWNED" -eq 1 ]; then
        "$BB" timeout -k 1 1 "$BB" rmdir "$LOCK" || :
        "$BB" timeout -k 1 1 "$BB" sync "$SD_MOUNT" || :
    fi
    exit "$result"
}
trap cleanup 0
trap 'exit 130' INT
trap 'exit 143' HUP TERM
tool mkdir -p "$BASE" || die 'Cannot create output base'
run_prefix=$BASE/run-$START_SECONDS-$$
number=0
while [ "$number" -lt "$MAX_RUN_NAMES" ]; do
    candidate=$run_prefix
    [ "$number" -eq 0 ] || candidate=$run_prefix-$number
    if tool mkdir "$candidate" 2>/dev/null; then OUT=$candidate; break; fi
    [ -e "$candidate" ] || [ -L "$candidate" ] || die 'Cannot create identity run'
    number=$((number + 1))
done
[ -n "$OUT" ] || die 'No unused identity run name'
printf 'IN_PROGRESS\n' > "$OUT/status.txt"
printf 'file\tresult\n' > "$OUT/capture.tsv"
printf 'identity_only=yes\nflash_devices_read=no\nmonotonic_start_seconds=%s\n' "$START_SECONDS" > "$OUT/collection.txt"
record() { printf '%s\t%s\n' "$1" "$2" >> "$OUT/capture.tsv"; }
capture() {
    budget
    input=$1; output=$2; cap=$3; required=$4
    if [ ! -r "$input" ] || [ ! -f "$input" ]; then
        record "$output" unavailable
        [ "$required" = no ] || die 'Required identity source is unavailable'
        return 0
    fi
    if tool head -c "$cap" "$input" > "$OUT/$output.part" 2>/dev/null; then
        size=$(tool stat -c %s "$OUT/$output.part") || die 'Cannot size identity output'
        uint "$size" && [ "$size" -le "$cap" ] || die 'Identity output exceeded cap'
        tool mv "$OUT/$output.part" "$OUT/$output" || die 'Cannot retain identity output'
        if [ "$size" -eq "$cap" ]; then record "$output" possibly-truncated; else record "$output" captured; fi
    else
        tool rm -f "$OUT/$output.part" || die 'Cannot remove failed identity output'
        record "$output" read-failed
        [ "$required" = no ] || die 'Required identity source could not be read'
    fi
}
source_hash() {
    budget
    hash_input=$1; hash_output=$2
    if [ ! -f "$hash_input" ]; then record "$hash_output" unavailable; return 0; fi
    if tool sha256sum "$hash_input" > "$OUT/$hash_output.part" 2>/dev/null; then
        tool mv "$OUT/$hash_output.part" "$OUT/$hash_output" || die 'Cannot retain source hash'
        record "$hash_output" captured
    else
        tool rm -f "$OUT/$hash_output.part" || die 'Cannot remove failed source hash'
        record "$hash_output" read-failed
    fi
}
for item in cpuinfo version meminfo mounts; do
    capture "$PROC/$item" "proc-$item.txt" "$MAX_FILE_BYTES" yes
done
capture "$PROC/mtd" proc-mtd.txt "$MAX_FILE_BYTES" no
capture "$PROC/uptime" proc-uptime.txt 4096 yes
tool uname -srm > "$OUT/kernel.txt" || die 'Cannot collect kernel identity'

mtd_count=0
for node in "$SYS"/class/mtd/mtd*; do
    id=${node##*/}; index=${id#mtd}
    uint "$index" || continue
    [ -d "$node" ] || continue
    mtd_count=$((mtd_count + 1))
    [ "$mtd_count" -le "$MAX_MTD_NODES" ] || die 'MTD metadata inventory exceeds cap'
    for attr in name type size erasesize writesize oobsize offset dev flags ecc_failures corrected_bits bad_blocks bbt_blocks; do
        capture "$node/$attr" "$id-$attr.txt" 4096 no
    done
done
printf 'sysfs_mtd_nodes=%s\n' "$mtd_count" >> "$OUT/collection.txt"

# Fixed startup paths only: never traverse configuration or the SD recursively.
script_number=0
for script in etc/init.sh etc/init.d/rcS etc/inittab init appfs/script/init.sh appfs/script/start.sh appfs/script/stop.sh init.sh; do
    budget
    script_number=$((script_number + 1))
    original=$STOCK_ROOT/$script
    resolved=$(tool readlink -f "$original" 2>/dev/null) || resolved=
    case "$resolved" in "$STOCK_ROOT"/etc/init.sh|"$STOCK_ROOT"/etc/init.d/*|"$STOCK_ROOT"/etc/inittab|"$STOCK_ROOT"/init|"$STOCK_ROOT"/init.sh|"$STOCK_ROOT"/appfs/script/*) ;; *)
        record "startup-$script_number.txt" unavailable-or-outside-startup-tree; continue;; esac
    printf '%s\t%s\n' "$script_number" "$resolved" >> "$OUT/startup-paths.tsv"
    capture "$resolved" "startup-$script_number.txt" "$MAX_FILE_BYTES" no
    source_hash "$resolved" "startup-$script_number-source-sha256.txt"
done

# Hash fixed stock candidates even if the background hook precedes app startup.
candidate_number=0
for candidate_path in appfs/bin/yy_cam appfs/yy_cam usr/bin/yy_cam bin/yy_cam; do
    candidate_number=$((candidate_number + 1))
    candidate_exe=$(tool readlink -f "$STOCK_ROOT/$candidate_path" 2>/dev/null) || candidate_exe=
    case "$candidate_exe" in "$STOCK_ROOT"/appfs/*/yy_cam|"$STOCK_ROOT"/appfs/yy_cam|"$STOCK_ROOT"/usr/bin/yy_cam|"$STOCK_ROOT"/bin/yy_cam)
        source_hash "$candidate_exe" "yy_cam-candidate-$candidate_number-sha256.txt";;
    *) record "yy_cam-candidate-$candidate_number-sha256.txt" unavailable-or-outside-stock-tree;; esac
done
# Stock starts the application after launching this hook in the background.
# This single brief pause is included in the overall monotonic budget.
tool sleep 2 || die 'Identity sampling pause failed'
scanned=0
processes=0
for process in "$PROC"/[0-9]*; do
    budget
    [ -d "$process" ] || continue
    scanned=$((scanned + 1))
    [ "$scanned" -le "$MAX_PROCESS_SCAN" ] || { record process-scan capped; break; }
    comm=$(tool head -c 64 "$process/comm" 2>/dev/null) || continue
    [ "$comm" = yy_cam ] || continue
    [ "$processes" -lt "$MAX_PROCESSES" ] || { record yy_cam-processes capped; break; }
    processes=$((processes + 1))
    pid=${process##*/}
    uint "$pid" || continue
    capture "$process/maps" "yy_cam-$pid-maps.txt" "$MAX_MAP_BYTES" no
    executable=$(tool readlink -f "$process/exe" 2>/dev/null) || executable=
    case "$executable" in *'
'*|*'	'*) executable=;; esac
    [ -n "$executable" ] || { record "yy_cam-$pid-exe.txt" unavailable; continue; }
    printf '%s\n' "$executable" > "$OUT/yy_cam-$pid-exe.txt"
    # A racing/deleted executable is optional. Never hash arbitrary device nodes.
    case "$executable" in "$STOCK_ROOT"/appfs/*|"$STOCK_ROOT"/usr/bin/*|"$STOCK_ROOT"/bin/*|"$STOCK_ROOT"/sbin/*) ;; *)
        record "yy_cam-$pid-sha256.txt" outside-stock-tree; continue;; esac
    if [ -f "$executable" ] && [ "${executable##*/}" = yy_cam ]; then
        source_hash "$process/exe" "yy_cam-$pid-sha256.txt"
    else record "yy_cam-$pid-sha256.txt" unavailable; fi
done
printf 'yy_cam_processes=%s\n' "$processes" >> "$OUT/collection.txt"
budget
printf 'IDENTITY_COLLECTION_COMPLETE\nexit_code=0\nfirmware_backup=no\n' > "$OUT/status.txt"
: > "$OUT/SHA256SUMS.part"
for file in "$OUT"/*; do
    [ "${file##*/}" != SHA256SUMS.part ] || continue
    [ -f "$file" ] && [ ! -L "$file" ] || die 'Unexpected identity output type'
    digest=$(tool sha256sum "$file") || die 'Cannot hash identity output'
    digest=${digest%% *}
    case "$digest" in ''|*[!0-9a-f]*) die 'Invalid identity checksum';; esac
    [ "${#digest}" -eq 64 ] || die 'Invalid identity checksum'
    printf '%s  %s\n' "$digest" "${file##*/}" >> "$OUT/SHA256SUMS.part"
    tool sync "$file" || die 'Cannot fsync identity output'
done
tool mv "$OUT/SHA256SUMS.part" "$OUT/SHA256SUMS" || die 'Cannot retain identity checksums'
(cd "$OUT" && tool sha256sum -c SHA256SUMS >/dev/null 2>&1) || die 'Identity checksum readback failed'
tool sync "$OUT/SHA256SUMS" || die 'Cannot fsync identity checksums'
tool sync "$OUT" || die 'Cannot fsync identity directory'
tool sync "$BASE" || die 'Cannot fsync identity base'
tool rmdir "$LOCK" || die 'Cannot remove owned identity lock'
LOCK_OWNED=0
tool sync "$SD_MOUNT" || die 'Cannot fsync SD root'
COMPLETE=1
printf '%s\n' 'Private identity collection complete; no firmware backup or device changes performed.'
