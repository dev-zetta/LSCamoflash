#!/bin/sh
. /mnt/LSCamoflash-fullhan/common.sh || exit 1
. /mnt/LSCamoflash-fullhan/onvif-common.sh || exit 1
regular "$BB" && [ -x "$BB" ] && root_user || exit 1
onvif_read_state || { fail "No valid ONVIF state; no signal sent"; exit 1; }
child_alive() {
    [ -d "$PROC/$1" ] || return 1
    state=$("$BB" sed 's/^.*) //' "$PROC/$1/stat" 2>/dev/null | "$BB" awk 'NR==1 {print $1}')
    [ "$state" != Z ] && [ "$state" != X ]
}
valid_owner_numbers() {
    case "$1:$2" in *[!0-9:]*|:*) return 1;; esac
    [ "$1" -gt 1 ] && [ -n "$2" ]
}
valid_owner_numbers "$server_pid" "$server_time" || { fail "Invalid ONVIF owner; no signal sent"; exit 1; }
if [ "$discovery_pid:$discovery_time" != 0:0 ]; then
    valid_owner_numbers "$discovery_pid" "$discovery_time" || { fail "Invalid discovery owner; no signal sent"; exit 1; }
fi
# Validate every surviving component before signaling any of them. A missing
# child may be cleaned up, but a reused or unrelated live PID remains protected.
server_live=0; discovery_live=0
if child_alive "$server_pid"; then
    onvif_owned "$server_pid" "$server_time" || { fail "ONVIF process ownership mismatch; no signal sent"; exit 1; }
    server_live=1
fi
if [ "$discovery_pid" != 0 ] && child_alive "$discovery_pid"; then
    onvif_discovery_owned "$discovery_pid" "$discovery_time" || { fail "Discovery ownership mismatch; no signal sent"; exit 1; }
    discovery_live=1
fi
if [ "$discovery_live" = 1 ]; then
    "$BB" kill -TERM "$discovery_pid" || exit 1
fi
[ "$server_live" = 0 ] || "$BB" kill -TERM "$server_pid" || exit 1
attempt=0
while child_alive "$server_pid" || { [ "$discovery_pid" != 0 ] && child_alive "$discovery_pid"; }; do
    attempt=$((attempt+1))
    [ "$attempt" -le 5 ] || { fail "Owned ONVIF service did not stop"; exit 1; }
    "$BB" sleep 1
done
# A crashed server may leave its PID file. Remove only its exact recorded PID.
if [ -e "$ONVIF_STATE/server.pid" ] || [ -L "$ONVIF_STATE/server.pid" ]; then
    regular "$ONVIF_STATE/server.pid" || { fail "Unexpected ONVIF PID file"; exit 1; }
    read -r recorded_pid extra < "$ONVIF_STATE/server.pid"
    [ "$recorded_pid" = "$server_pid" ] && [ -z "$extra" ] || { fail "ONVIF PID file mismatch"; exit 1; }
    "$BB" rm "$ONVIF_STATE/server.pid" || exit 1
fi
"$BB" rm "$ONVIF_STATE/owned" && "$BB" rmdir "$ONVIF_STATE" || exit 1
log_status "Optional Fullhan read-only ONVIF stopped" || true
printf '%s\n' "Optional Fullhan read-only ONVIF stopped"
