#!/bin/sh
# Manual pilot entry only. No vendor init, overlay, network or camera commands.
. /mnt/LSCamoflash-fullhan/common.sh || exit 1
regular "$BB" && [ -x "$BB" ] || { fail "Missing static pilot BusyBox"; exit 1; }
root_user || { fail "Root is required"; exit 1; }
identity || { fail "Fullhan firmware identity mismatch"; exit 1; }
trusted_mount || { fail "Expected a unique writable FAT MMC partition at /mnt"; exit 1; }
verify_payload || { fail "Pilot payload inventory or checksum mismatch"; exit 1; }
auth_features || { fail "BusyBox HTTP authentication support is required"; exit 1; }
auth_config || { fail "A regular authenticated httpd.conf is required"; exit 1; }
if [ -e "$ROOT/startup.log" ] || [ -L "$ROOT/startup.log" ]; then
    regular "$ROOT/startup.log" || { fail "Pilot log must be a regular file"; exit 1; }
fi
if "$BB" netstat -tln 2>/dev/null | "$BB" awk -v port="$PORT" '$1=="tcp" && $4 ~ ":" port "$" && $6=="LISTEN" {found=1} END {exit !found}'; then
    fail "Management port is already in use"; exit 1
fi
[ ! -e "$STATE" ] && [ ! -L "$STATE" ] || { fail "Pilot state already exists; refusing replacement"; exit 1; }
umask 077
"$BB" mkdir "$STATE" || exit 1
created_state=1
child=""
cleanup() {
    if [ -n "$child" ] && [ -n "${child_time:-}" ]; then
        retries=0
        while [ "$retries" -lt 3 ]; do
            if owned_http "$child" "$child_time"; then
                "$BB" kill -TERM "$child" 2>/dev/null || true
                break
            fi
            [ "$(start_time "$child")" = "$child_time" ] || break
            retries=$((retries+1))
            "$BB" sleep 1
        done
    fi
    [ ! -f "$STATE/pid" ] || "$BB" rm "$STATE/pid"
    [ "$created_state" = 0 ] || "$BB" rmdir "$STATE" 2>/dev/null || true
}
trap cleanup EXIT
trap 'exit 1' HUP INT TERM
# Neither loader overrides nor credentials are inherited by the stock process.
unset LD_PRELOAD LD_LIBRARY_PATH
"$BB" httpd -f -c "$ROOT/httpd.conf" -h "$ROOT/www" -p "$HTTP_BIND" >/dev/null 2>&1 &
child=$!
child_time=$(start_time "$child")
"$BB" sleep 1
owned_http "$child" "$child_time" || { fail "Management daemon did not start"; exit 1; }
printf '%s %s\n' "$child" "$child_time" > "$STATE/pid" || exit 1
log_status "Fullhan read-only management started" || exit 1
created_state=0
trap - EXIT HUP INT TERM
printf '%s\n' "Fullhan read-only management started on port $PORT"
