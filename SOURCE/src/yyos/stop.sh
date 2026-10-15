#!/bin/sh
[ -f /mnt/sdcard/LSCamoflash-yyos/common.sh ] && [ ! -L /mnt/sdcard/LSCamoflash-yyos/common.sh ] || exit 1
. /mnt/sdcard/LSCamoflash-yyos/common.sh || exit 1
regular "$BB" && [ -x "$BB" ] && root_user || exit 1
[ -d "$STATE" ] && [ ! -L "$STATE" ] && regular "$STATE/pid" || { fail 'No owned management state'; exit 1; }
read -r pid timestamp extra < "$STATE/pid" || exit 1
[ -z "$extra" ] && owned_http "$pid" "$timestamp" || { fail 'HTTP ownership mismatch; no signal sent'; exit 1; }
tool kill -TERM "$pid" || exit 1
attempt=0
while owned_http "$pid" "$timestamp"; do
    [ "$attempt" -lt 5 ] || { fail 'Owned HTTP daemon did not stop'; exit 1; }
    attempt=$((attempt + 1)); tool sleep 1
done
tool rm "$STATE/pid" && tool rmdir "$STATE" || exit 1
log_status 'YYOS read-only management stopped' || :
printf '%s\n' 'YYOS read-only management stopped'
