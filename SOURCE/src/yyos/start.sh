#!/bin/sh
# Separate HTTP management only; never execute or configure the stock camera.
[ -f /mnt/sdcard/LSCamoflash-yyos/common.sh ] && [ ! -L /mnt/sdcard/LSCamoflash-yyos/common.sh ] || exit 1
. /mnt/sdcard/LSCamoflash-yyos/common.sh || exit 1
regular "$BB" && [ -x "$BB" ] || { fail 'Missing static management BusyBox'; exit 1; }
root_user || { fail 'Root is required'; exit 1; }
identity || { fail 'YYOS firmware identity mismatch'; exit 1; }
trusted_mount || { fail 'Expected one writable FAT MMC partition at /mnt/sdcard'; exit 1; }
verify_payload || { fail 'Management payload inventory or checksum mismatch'; exit 1; }
auth_features && auth_config || { fail 'A supported authenticated httpd.conf is required'; exit 1; }
if [ -e "$ROOT/startup.log" ] || [ -L "$ROOT/startup.log" ]; then
    regular "$ROOT/startup.log" || { fail 'Management log must be a regular file'; exit 1; }
fi
port_listening "$PORT" && { fail 'Management port is already occupied'; exit 1; }
[ -d /tmp ] && [ ! -L /tmp ] || exit 1
[ ! -e "$STATE" ] && [ ! -L "$STATE" ] || { fail 'Management state already exists'; exit 1; }
umask 077
tool mkdir "$STATE" || exit 1
child=; child_time=; started=0
cleanup() {
    trap - EXIT HUP INT TERM
    if [ -n "$child" ] && [ -n "$child_time" ]; then
        attempt=0
        while [ "$attempt" -lt 3 ]; do
            if owned_http "$child" "$child_time"; then tool kill -TERM "$child" 2>/dev/null || :; break; fi
            [ "$(start_time "$child")" = "$child_time" ] || break
            attempt=$((attempt + 1)); tool sleep 1
        done
        attempt=0
        while owned_http "$child" "$child_time"; do
            [ "$attempt" -lt 5 ] || { fail 'Owned HTTP daemon remains; retaining state'; return 1; }
            attempt=$((attempt + 1)); tool sleep 1
        done
    fi
    if [ "$started" = 0 ]; then
        [ ! -e "$STATE/pid" ] || tool rm "$STATE/pid"
        tool rmdir "$STATE" 2>/dev/null || :
    fi
}
trap cleanup EXIT
trap 'exit 1' HUP INT TERM
unset LD_PRELOAD LD_LIBRARY_PATH
"$BB" httpd -f -c "$ROOT/httpd.conf" -h "$ROOT/www" -p "$HTTP_BIND" >/dev/null 2>&1 &
child=$!
child_time=$(start_time "$child")
[ -n "$child_time" ] || { fail 'Cannot identify owned HTTP child'; exit 1; }
printf '%s %s\n' "$child" "$child_time" > "$STATE/pid" || exit 1
attempt=0
while ! { owned_http "$child" "$child_time" && port_listening "$PORT"; }; do
    [ "$attempt" -lt 3 ] && [ "$(start_time "$child")" = "$child_time" ] || { fail 'Management daemon did not start'; exit 1; }
    attempt=$((attempt + 1)); tool sleep 1
done
log_status 'YYOS read-only management started' || exit 1
started=1
trap - EXIT HUP INT TERM
printf 'YYOS read-only management started on port %s\n' "$PORT"
