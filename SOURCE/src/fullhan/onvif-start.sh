#!/bin/sh
. /mnt/LSCamoflash-fullhan/common.sh || exit 1
. /mnt/LSCamoflash-fullhan/onvif-common.sh || exit 1
discovery_enabled=1
if [ "$#" = 1 ] && [ "$1" = --no-discovery ]; then
    discovery_enabled=0
elif [ "$#" != 0 ]; then
    fail "Usage: onvif-start.sh [--no-discovery]"; exit 1
fi
regular "$BB" && [ -x "$BB" ] && root_user && identity && trusted_mount && verify_payload || {
    fail "Fullhan ONVIF identity, mount or payload check failed"; exit 1;
}
regular "$ONVIF" && [ -x "$ONVIF" ] || exit 1
if [ "$discovery_enabled" = 1 ]; then
    regular "$DISCOVERY" && [ -x "$DISCOVERY" ] || exit 1
fi
onvif_credentials || { fail "Independent ONVIF credentials and UUID are required"; exit 1; }
onvif_memory || { fail "ONVIF requires at least 8192 kB MemAvailable"; exit 1; }
onvif_address=$(read_ipv4) || { fail "ONVIF requires one usable IPv4 address"; exit 1; }
read -r onvif_uuid < "$ROOT/onvif.uuid"
if "$BB" netstat -tlnu 2>/dev/null | "$BB" awk -v discovery="$discovery_enabled" '($1=="tcp" && $4~/:5000$/) || (discovery==1 && $1=="udp" && $4~/:3702$/) {found=1} END {exit !found}'; then
    fail "ONVIF or discovery port is already in use"; exit 1
fi
[ ! -e "$ONVIF_STATE" ] && [ ! -L "$ONVIF_STATE" ] || { fail "ONVIF state already exists"; exit 1; }
umask 077
"$BB" mkdir "$ONVIF_STATE" || exit 1
server_pid=""; server_time=""; discovery_pid=0; discovery_time=0
child_alive() {
    [ -n "$1" ] && [ "$1" != 0 ] && [ -d "$PROC/$1" ] || return 1
    state=$("$BB" sed 's/^.*) //' "$PROC/$1/stat" 2>/dev/null | "$BB" awk 'NR==1 {print $1}')
    [ "$state" != Z ] && [ "$state" != X ]
}
cleanup_child() {
    cleanup_pid="$1"; cleanup_time="$2"; cleanup_kind="$3"
    [ -n "$cleanup_pid" ] && [ "$cleanup_pid" != 0 ] && [ -n "$cleanup_time" ] || return 0
    cleanup_attempt=0
    while child_alive "$cleanup_pid" && [ "$(start_time "$cleanup_pid")" = "$cleanup_time" ]; do
        if { [ "$cleanup_kind" = server ] && onvif_owned "$cleanup_pid" "$cleanup_time"; } ||
           { [ "$cleanup_kind" = discovery ] && onvif_discovery_owned "$cleanup_pid" "$cleanup_time"; }; then
            "$BB" kill -TERM "$cleanup_pid" 2>/dev/null || true
            return 0
        fi
        cleanup_attempt=$((cleanup_attempt+1))
        [ "$cleanup_attempt" -lt 3 ] || return 0
        "$BB" sleep 1
    done
}
cleanup() {
    cleanup_child "$discovery_pid" "$discovery_time" discovery
    cleanup_child "$server_pid" "$server_time" server
    cleanup_attempt=0
    while child_alive "$server_pid" || child_alive "$discovery_pid"; do
        cleanup_attempt=$((cleanup_attempt+1))
        [ "$cleanup_attempt" -le 5 ] || { fail "ONVIF cleanup incomplete; state retained"; return; }
        "$BB" sleep 1
    done
    if [ -e "$ONVIF_STATE/server.pid" ] || [ -L "$ONVIF_STATE/server.pid" ]; then
        regular "$ONVIF_STATE/server.pid" || { fail "Unexpected ONVIF PID file; state retained"; return; }
        read -r recorded_pid extra < "$ONVIF_STATE/server.pid"
        [ "$recorded_pid" = "$server_pid" ] && [ -z "$extra" ] || { fail "ONVIF PID file mismatch; state retained"; return; }
        "$BB" rm "$ONVIF_STATE/server.pid" || return
    fi
    [ ! -f "$ONVIF_STATE/owned" ] || "$BB" rm "$ONVIF_STATE/owned"
    # Never recurse or remove files outside our exact private state inventory.
    "$BB" rmdir "$ONVIF_STATE" 2>/dev/null || true
}
trap cleanup EXIT
trap 'exit 1' HUP INT TERM
unset LD_PRELOAD LD_LIBRARY_PATH
onvif_action=execute
(onvif_arguments) >/dev/null 2>&1 &
server_pid=$!; server_time=$(start_time "$server_pid")
"$BB" sleep 1
onvif_owned "$server_pid" "$server_time" || { fail "ONVIF server did not start"; exit 1; }
if [ "$discovery_enabled" = 1 ]; then
    "$DISCOVERY" --interface wlan0 --xaddr "http://$onvif_address:$ONVIF_PORT/" --uuid "$onvif_uuid" >/dev/null 2>&1 &
    discovery_pid=$!; discovery_time=$(start_time "$discovery_pid")
    "$BB" sleep 1
    onvif_discovery_owned "$discovery_pid" "$discovery_time" || { fail "ONVIF discovery did not start"; exit 1; }
fi
printf '%s %s %s %s %s %s\n' "$server_pid" "$server_time" "$discovery_pid" "$discovery_time" "$onvif_address" "$onvif_uuid" > "$ONVIF_STATE/owned" || exit 1
log_status "Optional Fullhan read-only ONVIF started" || exit 1
trap - EXIT HUP INT TERM
printf '%s\n' "Optional Fullhan read-only ONVIF started on port $ONVIF_PORT"
[ "$discovery_enabled" = 1 ] || printf '%s\n' "Additional discovery disabled; use the ONVIF address directly"
