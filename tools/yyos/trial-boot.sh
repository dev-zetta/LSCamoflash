#!/bin/sh
# Exact YYOS trial boot: reuse the pinned recovery before every stock launch.
# This wrapper never enables media; its pinned companion may persist flags1->0.
set -eu
umask 077
LC_ALL=C
export LC_ALL
PROC=/proc
SYS=/sys
DEV=/dev
FS_ROOT=
APP_SHA=d76d632f41453f53d9d117582fc47073934f5e6ec9a9b7a0ebb1dd3824f6cba7
START_SHA=95c95547a3153d9020ffcf3334909c99ba96608af978180d8a1345b99e2d1b0f
INIT_SHA=ee00ed120a80c38b55dcd32c2e8a17d9a1340bac1118e0d7835b13adfd684d16
RECOVERY_SHA=9ee6fc266514ce90f96ec2453211d754c7dae2fd51ab5e8b78af19de3c8380fb
BB=
RUN=
CHILD=
LAUNCHES=0
COMPLETE=0
START_UPTIME=
HANDOFF=0

tool() {
    if [ -n "$START_UPTIME" ] && [ "$HANDOFF" = 0 ]; then
        read -r now rest < "$PROC/uptime" || return 1
        now=${now%%.*}
        case "$now" in ''|*[!0-9]*) return 1;; esac
        [ "$((now - START_UPTIME))" -le 420 ] || return 1
    fi
    case "$1" in
        timeout) "$BB" "$@";;
        stat|readlink|id|cat|head|mkdir) "$BB" timeout -k 2 10 "$BB" "$@";;
        *) "$BB" timeout -k 2 20 "$BB" "$@";;
    esac
}
status() {
    [ -n "$RUN" ] || return 0
    printf '%s\nrecovery_child_pid=%s\nwrapper_stock_launch_attempts=%s\nphysical_trial_verified=no\n' "$1" "$CHILD" "$LAUNCHES" > "$RUN/status.txt"
}
die() { status "HELD:$1"; COMPLETE=1; printf 'Trial boot held: %s\n' "$1" >&2; exit 1; }
cleanup() {
    code=$?
    trap - EXIT INT TERM HUP
    if [ "$COMPLETE" = 0 ] && [ -n "$RUN" ]; then status HELD_INTERRUPTED; fi
    exit "$code"
}
trap cleanup EXIT
trap 'exit 1' INT TERM HUP

no_symlinks() {
    case "$1" in /*) ;; *) return 1;; esac
    case "$1" in *[!A-Za-z0-9_./-]*|*/../*|*/./*) return 1;; esac
    current=
    old_ifs=$IFS; IFS=/
    for component in $1; do
        [ -n "$component" ] || continue
        current=$current/$component
        [ ! -L "$current" ] || { IFS=$old_ifs; return 1; }
    done
    IFS=$old_ifs
}
hash_file() {
    value=$(tool sha256sum "$1") || return 1
    value=${value%% *}
    [ "${#value}" = 64 ] || return 1
    case "$value" in *[!0-9a-f]*) return 1;; esac
    printf '%s\n' "$value"
}
mount_checked() {
    destination=$1; kind=$2
    no_symlinks "$destination" || return 1
    visible=$(tool stat -c %d "$destination") || return 1
    count=0; bad=0
    while read -r source point filesystem options rest; do
        [ "$point" = "$destination" ] || continue
        case "$kind:$source:$filesystem" in
            sd:"$DEV"/mmcblk0p1:vfat) ;;
            config:"$DEV"/mtdblock4:jffs2) ;;
            *) continue;;
        esac
        no_symlinks "$source" || return 1
        [ -b "$source" ] || continue # FIXTURE_BLOCK_CHECK
        numbers=$(tool stat -c %t:%T "$source") || return 1
        major=${numbers%:*}; minor=${numbers#*:}
        case "$major:$minor" in *[!0-9a-fA-F:]*) return 1;; esac
        [ -n "$major" ] && [ -n "$minor" ] && [ "${#major}" -le 5 ] && [ "${#minor}" -le 5 ] || return 1
        major=$((0x$major)); minor=$((0x$minor))
        encoded=$(((minor & 255) | ((major & 4095) << 8) | ((minor & 1048320) << 12)))
        [ "$visible" = "$encoded" ] || continue
        count=$((count + 1))
        case ",$options," in *,rw,*) ;; *) bad=1;; esac
    done < "$PROC/mounts"
    [ "$count" = 1 ] && [ "$bad" = 0 ] || return 1
    magic=$(tool stat -f -c %t "$destination") || return 1
    case "$kind:$magic" in sd:4d44|config:72b6) ;; *) return 1;; esac
}
no_camera() {
    processes=0
    for process in "$PROC"/[0-9]*; do
        [ -d "$process" ] || continue
        identity=${process##*/}
        case "$identity" in *[!0-9]*) continue;; esac
        processes=$((processes + 1)); [ "$processes" -le 256 ] || return 1
        comm=$(tool cat "$process/comm" 2>/dev/null) || comm=
        executable=$(tool readlink "$process/exe" 2>/dev/null) || executable=
        [ "$comm" != yy_cam ] && [ "$executable" != "$FS_ROOT/appfs/bin/yy_cam" ] || return 1
        if [ -z "$comm" ] && [ -z "$executable" ] && [ -d "$process" ]; then return 1; fi
    done
}
config_identity() {
    no_symlinks "$CONFIG" && [ -f "$CONFIG" ] || return 1
    info=$(tool stat -c '%a %u %g %s' "$CONFIG") || return 1
    set -- $info
    [ "$#" = 4 ] && [ "$2" = 0 ] && [ "$3" = 0 ] || return 1
    case "$1" in [0-7][0-7][0-7]) ;; *) return 1;; esac
    case "$4" in ''|*[!0-9]*) return 1;; esac
    [ "$4" -le 65536 ] && [ "$((0$1 & 022))" = 0 ] || return 1
    printf '%s\n' "$info"
}
regular_bounded() {
    no_symlinks "$1" && [ -f "$1" ] || return 1
    bytes=$(tool stat -c %s "$1") || return 1
    case "$bytes" in ''|*[!0-9]*) return 1;; esac
    [ "$bytes" -le "$2" ]
}
stock_guards() {
    hardware=$(tool awk -F: '/^Hardware[ \t]*:/ {gsub(/^[ \t]+|[ \t]+$/, "", $2); print $2}' "$PROC/cpuinfo") || return 1
    [ "$hardware" = AK3918AV130 ] || return 1
    for pair in "$FS_ROOT/appfs/bin/yy_cam:$APP_SHA" "$FS_ROOT/appfs/script/start.sh:$START_SHA" "$FS_ROOT/appfs/script/init.sh:$INIT_SHA"; do
        path=${pair%:*}; expected=${pair##*:}
        no_symlinks "$path" && [ -f "$path" ] || return 1
        [ "$(hash_file "$path")" = "$expected" ] || return 1
    done
    [ ! -e "$SD/yy_telnet_start" ] && [ ! -L "$SD/yy_telnet_start" ] || return 1
    regular_bounded "$SD/yy_debug.ini" 256 || return 1
    tool awk -F= -v start="$SD/telnetd" '
        /^mode=debug\r?$/ { mode++; next }
        $1=="start_sh" { sub(/\r$/, "", $2); if ($2!=start || NF!=2) exit 1; script++; next }
        /^[ \t]*$/ { next }
        { exit 1 }
        END { if (mode!=1 || script!=1) exit 1 }
    ' "$SD/yy_debug.ini" || return 1
    mount_checked "$SD" sd && mount_checked "$CONFIG_ROOT" config || return 1
    for item in type:nor size:262144 erasesize:4096 writesize:256 oobsize:0 offset:7995392; do
        key=${item%:*}; expected=${item##*:}
        [ "$(tool cat "$SYS/class/mtd/mtd4/$key")" = "$expected" ] || return 1
    done
    no_camera
}

[ "$#" = 1 ] || die argument_count
SD=$1
[ "$SD" = "$FS_ROOT/mnt/sdcard" ] && no_symlinks "$SD" || die sd_path
BB=$SD/busybox
[ -f "$BB" ] && [ -x "$BB" ] && [ ! -L "$BB" ] || die busybox
[ "$(tool id -u)" = 0 ] || die root_required
read -r START_UPTIME rest < "$PROC/uptime" || die uptime
START_UPTIME=${START_UPTIME%%.*}
case "$START_UPTIME" in ''|*[!0-9]*) die uptime;; esac
mount_checked "$SD" sd || die sd_mount
RAM=$FS_ROOT/tmp
no_symlinks "$RAM" && [ -d "$RAM" ] || die ram_path
[ "$(tool stat -f -c %t "$RAM")" = 1021994 ] || die ram_filesystem
LOCK=$RAM/lscamoflash-yyos-trial-boot.lock
no_symlinks "$LOCK" || die trial_lock
tool mkdir "$LOCK" 2>/dev/null || die trial_lock
printf '%s\n' "$$" > "$LOCK/owner-pid"
BASE=$SD/trial-boot
no_symlinks "$BASE" || die output_path
if [ -e "$BASE" ]; then [ -d "$BASE" ] || die output_path; else tool mkdir "$BASE" || die output_directory; fi
number=0
while [ "$number" -lt 32 ]; do
    candidate=$BASE/run-$$-$number
    if tool mkdir "$candidate" 2>/dev/null; then RUN=$candidate; break; fi
    number=$((number + 1))
done
[ -n "$RUN" ] || die output_collision
exec >> "$RUN/trial-boot.log" 2>&1
status CHECKING_RECOVERY
RECOVERY=$SD/recover-native-off.sh
regular_bounded "$RECOVERY" 32768 || die recovery_path
[ "$(hash_file "$RECOVERY")" = "$RECOVERY_SHA" ] || die recovery_hash
PRIOR_NAMES=
PRIOR_COUNT=0
PRIOR_BASE=$SD/native-recovery
no_symlinks "$PRIOR_BASE" || die prior_runs
if [ -e "$PRIOR_BASE" ]; then
    [ -d "$PRIOR_BASE" ] || die prior_runs
    for prior in "$PRIOR_BASE"/run-*; do
        [ -e "$prior" ] || [ -L "$prior" ] || continue
        no_symlinks "$prior" && [ -d "$prior" ] || die prior_runs
        prior_name=${prior##*/}; suffix=${prior_name#run-}
        prior_pid=${suffix%-*}; prior_index=${suffix##*-}
        case "$prior_pid" in ''|0|*[!0-9]*) die prior_runs;; esac
        [ "${#prior_pid}" -le 10 ] || die prior_runs
        case "$prior_index" in 0|[1-9]|[12][0-9]|3[01]) ;; *) die prior_runs;; esac
        [ "$prior_name" = "run-$prior_pid-$prior_index" ] || die prior_runs
        PRIOR_COUNT=$((PRIOR_COUNT + 1)); [ "$PRIOR_COUNT" -le 512 ] || die prior_runs
        PRIOR_NAMES="$PRIOR_NAMES $prior_name"
    done
fi
printf '%s\n' "$PRIOR_NAMES" > "$RUN/prior-recovery-runs.txt"
tool sync "$RUN/prior-recovery-runs.txt" "$RUN" "$BASE" "$SD" || die output_sync
# BusyBox timeout execs the target in its own PID; the recovery RAM lock must
# identify this direct child. It sends signals only to that owned child PID.
"$BB" timeout -k 2 350 "$BB" sh "$RECOVERY" "$SD" </dev/null &
CHILD=$!
status RECOVERY_RUNNING
result=0
wait "$CHILD" || result=$?
printf '%s\n' "$result" > "$RUN/recovery-exit.txt"
case "$result" in
    0)
        # Recovery already disabled the flags and invoked stock itself.
        status RECOVERY_OFF_STOCK_START_RETURNED
        tool sync "$RUN/status.txt" "$RUN/recovery-exit.txt" "$RUN" || die output_sync
        COMPLETE=1
        exit 0;;
    3) ;;
    *) die recovery_failed;;
esac

CONFIG_ROOT=$FS_ROOT/config
CONFIG=$CONFIG_ROOT/param.conf
RECOVERY_LOCK=$RAM/lscamoflash-yyos-native-recovery.lock
regular_bounded "$RECOVERY_LOCK/owner-pid" 32 || die recovery_owner
[ "$(tool cat "$RECOVERY_LOCK/owner-pid")" = "$CHILD" ] || die recovery_owner
RECOVERY_RUN=
matching=0
number=0
while [ "$number" -lt 32 ]; do
    candidate=$SD/native-recovery/run-$CHILD-$number
    if [ -e "$candidate" ] || [ -L "$candidate" ]; then
        no_symlinks "$candidate" && [ -d "$candidate" ] || die recovery_run
        name=${candidate##*/}
        case " $PRIOR_NAMES " in
            *" $name "*) ;;
            *) matching=$((matching + 1)); RECOVERY_RUN=$candidate;;
        esac
    fi
    number=$((number + 1))
done
[ "$matching" = 1 ] || die recovery_run_count
regular_bounded "$RECOVERY_RUN/status.txt" 256 || die recovery_status
tool awk 'NR==1 {if($0!="ALREADY_OFF_HOLD_DEBUG")bad=1}
    NR==2 {if($0!="config_modified=0")bad=1}
    NR==3 {if($0!="stock_launch_attempts=0")bad=1}
    NR==4 {if($0!="physical_recovery_verified=no")bad=1}
    END {exit bad || NR!=4}' "$RECOVERY_RUN/status.txt" || die recovery_status
regular_bounded "$RECOVERY_RUN/plan.txt" 256 || die recovery_plan
tool awk 'NR==1 {if($0!="enabled_values=0")bad=1}
    NR==2 {if($0!="rtsp_prior=0" && $0!="rtsp_prior=missing_default0")bad=1}
    NR==3 {if($0!="onvif_prior=0" && $0!="onvif_prior=missing_default0")bad=1}
    END {exit bad || NR!=3}' "$RECOVERY_RUN/plan.txt" || die recovery_plan
stock_guards || die stock_guards
ORIGINAL_INFO=$(config_identity) || die config_identity
ORIGINAL_HASH=$(hash_file "$CONFIG") || die config_hash
regular_bounded "$RECOVERY_RUN/original-param.conf" 65536 &&
    regular_bounded "$RECOVERY_RUN/off-param.conf" 65536 &&
    regular_bounded "$RECOVERY_RUN/original-metadata.txt" 512 || die preserved_state
[ "$(hash_file "$RECOVERY_RUN/original-param.conf")" = "$ORIGINAL_HASH" ] &&
    [ "$(hash_file "$RECOVERY_RUN/off-param.conf")" = "$ORIGINAL_HASH" ] || die preserved_hash
set -- $ORIGINAL_INFO
expected_metadata=$(printf 'sha256=%s\nmode=%s\nuid=%s\ngid=%s\nbytes=%s' "$ORIGINAL_HASH" "$1" "$2" "$3" "$4")
[ "$(tool cat "$RECOVERY_RUN/original-metadata.txt")" = "$expected_metadata" ] || die preserved_metadata
printf '%s\n' "$RECOVERY_RUN" > "$RUN/recovery-run.txt"
status ALREADY_OFF_FALLBACK_VALIDATED
tool sync "$RUN/status.txt" "$RUN/recovery-run.txt" "$RUN" || die output_sync
# Repeat the mutable checks immediately before the single fallback handoff.
stock_guards || die final_stock_guards
[ "$(config_identity)" = "$ORIGINAL_INFO" ] && [ "$(hash_file "$CONFIG")" = "$ORIGINAL_HASH" ] || die config_changed
LAUNCHES=1
status FALLBACK_STOCK_START_ATTEMPTED
HANDOFF=1
stock_exit=0
(
    unset LD_PRELOAD
    PATH=$FS_ROOT/appfs/bin:$FS_ROOT/bin:$FS_ROOT/sbin:$FS_ROOT/usr/bin:$FS_ROOT/usr/sbin
    LD_LIBRARY_PATH=$FS_ROOT/appfs/lib
    export PATH LD_LIBRARY_PATH
    tool timeout -k 2 30 "$FS_ROOT/bin/sh" "$FS_ROOT/appfs/script/start.sh"
) </dev/null >/dev/null 2>&1 || stock_exit=$?
printf '%s\n' "$stock_exit" > "$RUN/stock-start-exit.txt"
[ "$stock_exit" = 0 ] || die stock_start_failed
HTTP=$SD/LSCamoflash-yyos/start.sh
if no_symlinks "$HTTP" && [ -f "$HTTP" ]; then
    tool timeout -k 2 20 "$BB" sh "$HTTP" </dev/null > "$RUN/http-start.log" 2>&1 || :
fi
status ALREADY_OFF_STOCK_START_RETURNED
tool sync "$RUN/status.txt" "$RUN/stock-start-exit.txt" "$RUN" || die output_sync
COMPLETE=1
exit 0
