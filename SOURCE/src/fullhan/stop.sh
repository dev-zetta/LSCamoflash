#!/bin/sh
. /mnt/LSCamoflash-fullhan/common.sh || exit 1
regular "$BB" && [ -x "$BB" ] && root_user || exit 1
[ -d "$STATE" ] && [ ! -L "$STATE" ] && regular "$STATE/pid" || { fail "No owned pilot state"; exit 1; }
read -r pid timestamp extra < "$STATE/pid"
[ -z "$extra" ] && owned_http "$pid" "$timestamp" || { fail "Pilot PID ownership mismatch; no signal sent"; exit 1; }
"$BB" kill -TERM "$pid" || exit 1
attempt=0
while owned_http "$pid" "$timestamp"; do
    attempt=$((attempt+1))
    [ "$attempt" -le 5 ] || { fail "Owned daemon did not stop"; exit 1; }
    "$BB" sleep 1
done
"$BB" rm "$STATE/pid" && "$BB" rmdir "$STATE" || exit 1
# Logging failure after a successful stop does not affect stock services.
log_status "Fullhan read-only management stopped" || true
printf '%s\n' "Fullhan read-only management stopped"
