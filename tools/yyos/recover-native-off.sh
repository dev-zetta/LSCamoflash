#!/bin/sh
# Exact3225722 recovery, invoked by the verified native SD launcher in debug mode.
# This deliberately writes the JFFS2 configuration, never raw MTD/firmware.
# Output contains private configuration/kernel data; keep the entire run private.
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
RUN=
TEMP=
TEMP_OWNED=0
MODIFIED=0
LAUNCHES=0
COMPLETE=0
BB=
START_UPTIME=
HANDOFF=0

tool() {
    if [ -n "$START_UPTIME" ] && [ "$HANDOFF" = 0 ]; then
        read -r now rest < "$PROC/uptime" || return 1
        now=${now%%.*}
        case "$now" in ''|*[!0-9]*) return 1;; esac
        [ "$((now - START_UPTIME))" -le 240 ] || return 1
    fi
    case "$1" in
        timeout) "$BB" "$@";;
        stat|readlink|id|cat|head|mkdir|rm|chmod|chown) "$BB" timeout -k 2 10 "$BB" "$@";;
        *) "$BB" timeout -k 2 20 "$BB" "$@";;
    esac
}
status() {
    [ -n "$RUN" ] || return 0
    { printf '%s\n' "$1"; printf 'config_modified=%s\nstock_launch_attempts=%s\nphysical_recovery_verified=no\n' "$MODIFIED" "$LAUNCHES"; } > "$RUN/status.txt"
}
die() { status "FAILED:$1"; COMPLETE=1; printf 'Recovery held: %s\n' "$1" >&2; exit 1; }
cleanup() {
    code=$?
    trap - EXIT INT TERM HUP
    if [ "$TEMP_OWNED" = 1 ]; then tool rm -f "$TEMP" || :; fi
    if [ "$COMPLETE" = 0 ] && [ -n "$RUN" ]; then status FAILED_INTERRUPTED; fi
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
snapshot() {
    for name in meminfo uptime mounts; do
        tool head -c 65536 "$PROC/$name" > "$RUN/$name.txt" 2>/dev/null || :
    done
    tool timeout -k 2 5 "$BB" dmesg 2>/dev/null | tool head -c 65536 > "$RUN/dmesg.txt" || :
    : > "$RUN/processes.txt"
    seen=0
    for process in "$PROC"/[0-9]*; do
        [ -d "$process" ] || continue
        seen=$((seen + 1)); [ "$seen" -le 64 ] || break
        comm=$(tool head -c 64 "$process/comm" 2>/dev/null) || continue
        printf '%s %s\n' "${process##*/}" "$comm" >> "$RUN/processes.txt"
    done
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
# Retain this lock for the boot, including failures/holds. Never infer that an
# old PID is safe to remove; a second invocation must not launch stock again.
RAM=$FS_ROOT/tmp
no_symlinks "$RAM" && [ -d "$RAM" ] || die ram_path
[ "$(tool stat -f -c %t "$RAM")" = 1021994 ] || die ram_filesystem
LOCK=$RAM/lscamoflash-yyos-native-recovery.lock
no_symlinks "$LOCK" || die recovery_lock
tool mkdir "$LOCK" 2>/dev/null || die recovery_lock
printf '%s\n' "$$" > "$LOCK/owner-pid"
BASE=$SD/native-recovery
no_symlinks "$BASE" || die output_path
if [ -e "$BASE" ]; then [ -d "$BASE" ] || die output_path; else tool mkdir "$BASE" || die output_directory; fi
number=0
while [ "$number" -lt 32 ]; do
    candidate=$BASE/run-$$-$number
    if tool mkdir "$candidate" 2>/dev/null; then RUN=$candidate; break; fi
    number=$((number + 1))
done
[ -n "$RUN" ] || die output_collision
exec >> "$RUN/recovery.log" 2>&1
status VALIDATING
snapshot

hardware=$(tool awk -F: '/^Hardware[ \t]*:/ {gsub(/^[ \t]+|[ \t]+$/, "", $2); print $2}' "$PROC/cpuinfo") || die cpu_read
[ "$hardware" = AK3918AV130 ] || die cpu_profile
for pair in "$FS_ROOT/appfs/bin/yy_cam:$APP_SHA" "$FS_ROOT/appfs/script/start.sh:$START_SHA" "$FS_ROOT/appfs/script/init.sh:$INIT_SHA"; do
    path=${pair%:*}; expected=${pair##*:}
    no_symlinks "$path" && [ -f "$path" ] || die stock_path
    [ "$(hash_file "$path")" = "$expected" ] || die stock_hash
done
[ ! -e "$SD/yy_telnet_start" ] && [ ! -L "$SD/yy_telnet_start" ] || die normal_hook_present
no_symlinks "$SD/yy_debug.ini" && [ -f "$SD/yy_debug.ini" ] || die debug_entry
tool awk -F= -v start="$SD/telnetd" '
    /^mode=debug\r?$/ { mode++; next }
    $1=="start_sh" { sub(/\r$/, "", $2); if ($2!=start || NF!=2) exit 1; script++; next }
    /^[ \t]*$/ { next }
    { exit 1 }
    END { if (mode!=1 || script!=1) exit 1 }
' "$SD/yy_debug.ini" || die debug_entry
CONFIG_ROOT=$FS_ROOT/config
CONFIG=$CONFIG_ROOT/param.conf
mount_checked "$CONFIG_ROOT" config || die config_mount
for item in type:nor size:262144 erasesize:4096 writesize:256 oobsize:0 offset:7995392; do
    key=${item%:*}; expected=${item##*:}
    actual=$(tool cat "$SYS/class/mtd/mtd4/$key") || die config_geometry
    [ "$actual" = "$expected" ] || die config_geometry
done
no_camera || die camera_already_running
ORIGINAL_INFO=$(config_identity) || die config_identity
set -- $ORIGINAL_INFO
MODE=$1; OWNER=$2; GROUP=$3; SIZE=$4
ORIGINAL_HASH=$(hash_file "$CONFIG") || die config_hash
tool cp "$CONFIG" "$RUN/original-param.conf" || die config_preservation
[ "$(hash_file "$RUN/original-param.conf")" = "$ORIGINAL_HASH" ] &&
    [ "$(hash_file "$CONFIG")" = "$ORIGINAL_HASH" ] || die config_changed
printf 'sha256=%s\nmode=%s\nuid=%s\ngid=%s\nbytes=%s\n' "$ORIGINAL_HASH" "$MODE" "$OWNER" "$GROUP" "$SIZE" > "$RUN/original-metadata.txt"
tool sync "$RUN/original-param.conf" "$RUN/original-metadata.txt" "$RUN" "$BASE" "$SD" || die preservation_sync

# Decode a bounded byte stream so CRLF, whitespace and a missing final newline
# survive exactly. Values unrelated to the two flags are opaque and never logged.
tool od -An -v -t u1 "$RUN/original-param.conf" > "$RUN/input-bytes.txt" || die config_read
tool awk -v expected="$SIZE" -v plan="$RUN/plan.txt" '
function reject() { invalid=1; exit 1 }
function line(first,last,    i,text,s,section_line,key,equal,value,tail,prefix,pos,canonical) {
    text=""; for(i=first;i<=last;i++) text=text sprintf("%c", bytes[i])
    s=text; sub(/\r$/, "", s); if(index(s,"\r")) reject()
    if(s ~ /^[ \t]*$/ || s ~ /^[ \t]*[#;]/) return
    if(s ~ /^[ \t]*\[/) {
        if(s !~ /^[ \t]*\[[A-Za-z0-9_.-]+\][ \t]*([#;].*)?$/) reject()
        section_line=s; sub(/^[ \t]*\[/,"",section_line); sub(/\].*$/,"",section_line)
        section=tolower(section_line); if(sections[section]++) reject(); return
    }
    if(section=="" || s !~ /^[ \t]*[A-Za-z0-9_.-]+[ \t]*=/) reject()
    equal=index(s,"="); key=substr(s,1,equal-1); gsub(/^[ \t]+|[ \t]+$/,"",key)
    key=tolower(key); canonical=section ":" key; if(keys[canonical]++) reject()
    if(canonical!="rtsp:rtsp_on_off" && canonical!="onvif:onvif_on_off") return
    value=substr(s,equal+1)
    if(value !~ /^[ \t]*[01][ \t]*([#;].*)?$/) reject()
    prefix=value; sub(/[^ \t].*$/,"",prefix); pos=first+equal+length(prefix)
    prior[canonical]=(bytes[pos]==49 ? 1 : 0)
    if(bytes[pos]==49) { bytes[pos]=48; enabled++ }
}
{ for(i=1;i<=NF;i++) { if($i !~ /^[0-9]+$/ || $i>255 || $i==0 || ($i<32 && $i!=9 && $i!=10 && $i!=13) || $i==127) reject(); bytes[++count]=$i } }
END {
    if(invalid || count!=expected) exit 1
    first=1
    for(last=1;last<=count;last++) if(bytes[last]==10) { line(first,last-1); first=last+1 }
    if(first<=count) line(first,count)
    if(invalid) exit 1
    print "enabled_values=" enabled+0 > plan
    print "rtsp_prior=" (keys["rtsp:rtsp_on_off"] ? prior["rtsp:rtsp_on_off"] : "missing_default0") > plan
    print "onvif_prior=" (keys["onvif:onvif_on_off"] ? prior["onvif:onvif_on_off"] : "missing_default0") > plan
    close(plan)
    for(i=1;i<=count;i++) printf "%c", bytes[i]
}' "$RUN/input-bytes.txt" > "$RUN/off-param.conf" || die invalid_ini
tool rm "$RUN/input-bytes.txt" || die scratch_cleanup
enabled=$(tool head -n 1 "$RUN/plan.txt") || die plan_read
case "$enabled" in enabled_values=1|enabled_values=2) ;;
    enabled_values=0) status ALREADY_OFF_HOLD_DEBUG; COMPLETE=1; exit 3;;
    *) die plan_invalid;; esac
OFF_HASH=$(hash_file "$RUN/off-param.conf") || die off_hash
[ "$(tool stat -c %s "$RUN/off-param.conf")" = "$SIZE" ] || die byte_length
no_camera || die camera_already_running
mount_checked "$CONFIG_ROOT" config || die config_mount
[ "$(config_identity)" = "$ORIGINAL_INFO" ] && [ "$(hash_file "$CONFIG")" = "$ORIGINAL_HASH" ] || die config_changed
TEMP=$CONFIG_ROOT/.param.conf.native-off-$$
no_symlinks "$TEMP" && [ ! -e "$TEMP" ] && [ ! -L "$TEMP" ] || die temporary_collision
set -C
exec 3> "$TEMP"
TEMP_OWNED=1
set +C
tool cat "$RUN/off-param.conf" >&3 || die temporary_copy
exec 3>&-
tool chown "$OWNER:$GROUP" "$TEMP" || die temporary_owner
tool chmod "$MODE" "$TEMP" || die temporary_mode
tool sync "$TEMP" || die temporary_sync
[ "$(hash_file "$TEMP")" = "$OFF_HASH" ] || die temporary_hash
no_camera || die camera_already_running
mount_checked "$CONFIG_ROOT" config || die config_mount
[ "$(config_identity)" = "$ORIGINAL_INFO" ] && [ "$(hash_file "$CONFIG")" = "$ORIGINAL_HASH" ] || die config_changed
tool mv -T "$TEMP" "$CONFIG" || die atomic_rename
TEMP_OWNED=0
MODIFIED=1
tool sync "$CONFIG_ROOT" || die commit_sync
[ "$(hash_file "$CONFIG")" = "$OFF_HASH" ] && [ "$(config_identity)" = "$ORIGINAL_INFO" ] || die commit_verification
status CONFIG_VERIFIED_OFF
snapshot
no_camera || die camera_started_before_handoff
LAUNCHES=1
status STOCK_START_ATTEMPTED
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
if [ -f "$HTTP" ] && [ ! -L "$HTTP" ]; then
    tool timeout -k 2 20 "$BB" sh "$HTTP" </dev/null > "$RUN/http-start.log" 2>&1 || :
fi
status CONFIG_OFF_STOCK_START_RETURNED
tool sync "$RUN/status.txt" "$RUN/stock-start-exit.txt" "$RUN" || die output_sync
COMPLETE=1
exit 0
