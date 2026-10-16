#!/bin/sh
[ -f /mnt/sdcard/LSCamoflash-yyos-ssh/common.sh ] && [ ! -L /mnt/sdcard/LSCamoflash-yyos-ssh/common.sh ] || exit 1
. /mnt/sdcard/LSCamoflash-yyos-ssh/common.sh || exit 1
regular "$BB" && [ -x "$BB" ] && regular "$DB" && [ -x "$DB" ] || exit 1
identity && trusted_mount && verify_payload || { fail 'SSH profile, mount or payload refused'; exit 1; }
if [ ! -e "$ROOT/ssh.enabled" ] && [ ! -L "$ROOT/ssh.enabled" ]; then printf '%s\n' 'SSH is disabled'; exit 0; fi
key_inputs || { fail 'Explicit SSH marker and single provisioned Ed25519 keys required'; exit 1; }
port_listening && { fail 'SSH port is occupied'; exit 1; }
[ ! -e "$STATE" ] && [ ! -L "$STATE" ] || { fail 'SSH state already exists'; exit 1; }
umask 077
tool mkdir "$STATE" || exit 1
child=; child_time=; bind=; success=0
cleanup() {
    trap - EXIT INT TERM HUP
    if [ -n "$child" ] && [ -z "$child_time" ]; then fail 'SSH child identity unknown; state retained'; return 1; fi
    if [ -n "$child" ] && [ -n "$child_time" ]; then
        count=0
        while ! owned_ssh "$child" "$child_time" "$bind"; do
            [ "$(start_time "$child")" = "$child_time" ] && [ "$count" -lt 3 ] || break
            count=$((count+1)); tool sleep 1
        done
        owned_ssh "$child" "$child_time" "$bind" && tool kill -TERM "$child" 2>/dev/null || :
        count=0
        while owned_ssh "$child" "$child_time" "$bind"; do
            [ "$count" -lt 5 ] || { fail 'Owned SSH remains; state retained'; return 1; }
            count=$((count+1)); tool sleep 1
        done
        no_remaining_dropbear || { fail 'SSH sessions remain; state retained'; return 1; }
    fi
    [ "$success" = 1 ] || remove_state
}
trap cleanup EXIT
trap 'exit 1' INT TERM HUP
for file in authorized_keys dropbear_ed25519_host_key; do
    tool cp "$ROOT/$file" "$STATE/$file" && tool chmod 600 "$STATE/$file" || exit 1
    before=$(tool sha256sum "$ROOT/$file") && after=$(tool sha256sum "$STATE/$file") || exit 1
    [ "${before%% *}" = "${after%% *}" ] || exit 1
done
read -r started rest < "$UPTIME" || exit 1
started=${started%%.*}; case "$started" in ''|*[!0-9]*) exit 1;; esac
count=0
while ! bind=$(read_ip); do
    read -r now rest < "$UPTIME" || exit 1
    now=${now%%.*}; case "$now" in ''|*[!0-9]*) exit 1;; esac
    [ "$count" -lt "$WAIT_SECONDS" ] && [ "$((now-started))" -lt "$WAIT_SECONDS" ] || { fail 'Private WiFi address unavailable'; exit 1; }
    count=$((count+1)); tool sleep 1
done
port_listening && { fail 'SSH port became occupied'; exit 1; }
unset LD_PRELOAD LD_LIBRARY_PATH
"$DB" -F -s -j -k -D "$STATE" -r "$STATE/dropbear_ed25519_host_key" -P "$STATE/dropbear.pid" -p "$bind:$PORT" -I 600 -K 30 -T 3 </dev/null >/dev/null 2>&1 &
child=$!; child_time=$(start_time "$child")
[ -n "$child_time" ] || { fail 'Cannot identify SSH child'; exit 1; }
printf '%s %s %s\n' "$child" "$child_time" "$bind" > "$STATE/owner" || exit 1
count=0
while ! { owned_ssh "$child" "$child_time" "$bind" && port_listening; }; do
    [ "$count" -lt 3 ] && [ "$(start_time "$child")" = "$child_time" ] || { fail 'SSH daemon did not start'; exit 1; }
    count=$((count+1)); tool sleep 1
done
regular "$STATE/dropbear.pid" && [ "$(tool cat "$STATE/dropbear.pid")" = "$child" ] || exit 1
log_status 'YYOS key-only SSH started' || exit 1
success=1
trap - EXIT INT TERM HUP
printf 'YYOS key-only SSH started on port %s\n' "$PORT"
