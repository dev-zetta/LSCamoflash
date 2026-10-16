#!/bin/sh
[ -f /mnt/sdcard/LSCamoflash-yyos-ssh/common.sh ] && [ ! -L /mnt/sdcard/LSCamoflash-yyos-ssh/common.sh ] || exit 1
. /mnt/sdcard/LSCamoflash-yyos-ssh/common.sh || exit 1
regular "$BB" && [ -x "$BB" ] && [ "$(tool id -u)" = 0 ] || exit 1
no_symlinks "$STATE" && [ -d "$STATE" ] && regular "$STATE/owner" || { fail 'No owned SSH state'; exit 1; }
read -r child child_time bind extra < "$STATE/owner" || exit 1
[ -z "$extra" ] && owned_ssh "$child" "$child_time" "$bind" || { fail 'SSH ownership mismatch; no signal sent'; exit 1; }
frozen=0
resume() {
    trap - EXIT INT TERM HUP
    if [ "$frozen" = 1 ] && owned_ssh "$child" "$child_time" "$bind"; then tool kill -CONT "$child" 2>/dev/null || :; fi
}
trap resume EXIT
trap 'exit 1' INT TERM HUP
frozen=1
tool kill -STOP "$child" || exit 1
count=0
while :; do
    owned_ssh "$child" "$child_time" "$bind" || exit 1
    state=$(tool sed 's/^.*) //' "$PROC/$child/stat" | tool awk '{print $1}') || exit 1
    [ "$state" = T ] && break
    [ "$count" -lt 3 ] || { fail 'SSH listener did not pause'; exit 1; }
    count=$((count+1)); tool sleep 1
done
no_direct_children "$child" || { fail 'SSH sessions are active; close them before stopping'; exit 1; }
owned_ssh "$child" "$child_time" "$bind" && tool kill -TERM "$child" || exit 1
tool kill -CONT "$child" || exit 1
frozen=0
count=0
while owned_ssh "$child" "$child_time" "$bind"; do
    [ "$count" -lt 5 ] || { fail 'Owned SSH did not stop; state retained'; exit 1; }
    count=$((count+1)); tool sleep 1
done
no_remaining_dropbear || { fail 'SSH sessions remain; state retained'; exit 1; }
remove_state || exit 1
trap - EXIT INT TERM HUP
log_status 'YYOS key-only SSH stopped' || :
printf '%s\n' 'YYOS key-only SSH stopped'
