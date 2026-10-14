#!/bin/sh
# Optional independent service. No stock configuration or library changes.
ONVIF="$ROOT/bin/onvif_srvd"
DISCOVERY="$ROOT/bin/fullhan-discovery"
ONVIF_STATE="/tmp/lscamoflash-fullhan-onvif"
ONVIF_PORT=5000

onvif_credentials() {
    regular "$ROOT/onvif.auth" && regular "$ROOT/onvif.uuid" || return 1
    "$BB" awk 'NR==1 {if($0 !~ /^[A-Za-z0-9_.-]+$/ || length($0)>32)bad=1}
        NR==2 {if(length($0)<1 || length($0)>128 || $0~/[^ -~]/)bad=1}
        END {exit bad || NR!=2}' "$ROOT/onvif.auth" || return 1
    "$BB" awk 'NR==1 {n=split($0,a,"-");if(n!=5 || length(a[1])!=8 || length(a[2])!=4 || length(a[3])!=4 || length(a[4])!=4 || length(a[5])!=12 || a[3]!~/^4/ || a[4]!~/^[89ab]/)bad=1;for(i=1;i<=n;i++)if(a[i]!~/^[0-9a-f]+$/)bad=1}
        END {exit bad || NR!=1}' "$ROOT/onvif.uuid"
}

onvif_memory() {
    "$BB" awk '$1=="MemAvailable:" && $2~/^[0-9]+$/ && $3=="kB" {n++;available=$2}
        END {exit n!=1 || available<8192}' "$MEMINFO"
}

# This one argument list is shared by execution and process ownership checks.
onvif_arguments() {
    set -- --no_fork --no_close --pid_file "$ONVIF_STATE/server.pid" \
        --auth_file "$ROOT/onvif.auth" --model SZB22705 --manufacturer LSC \
        --ifs wlan0 --port "$ONVIF_PORT" --scope onvif://www.onvif.org/type/video_encoder \
        --scope onvif://www.onvif.org/name/LSCamoflash --scope onvif://www.onvif.org/hardware/SZB22705 \
        --scope onvif://www.onvif.org/location/anywhere \
        --firmware_ver 7.6.23 --hardware_id FH8626V100 --serial_num "$onvif_uuid" \
        --name main --width 1920 --height 1080 --url "rtsp://$onvif_address:8554/main" --type H264 \
        --name sub --width 640 --height 360 --url "rtsp://$onvif_address:8554/sub" --type H264
    case "$onvif_action" in
        execute) exec "$ONVIF" "$@";;
        inspect) printf '%s\n' "$ONVIF" "$@";;
        *) return 1;;
    esac
}

onvif_owned() {
    onvif_pid="$1"; onvif_time="$2"
    case "$onvif_pid:$onvif_time" in *[!0-9:]*|:*) return 1;; esac
    [ "$onvif_pid" -gt 1 ] && [ -n "$onvif_time" ] || return 1
    [ "$(start_time "$onvif_pid")" = "$onvif_time" ] || return 1
    [ "$("$BB" readlink "$PROC/$onvif_pid/exe" 2>/dev/null)" = "$ONVIF" ] || return 1
    actual=$("$BB" tr '\000' '\n' < "$PROC/$onvif_pid/cmdline" 2>/dev/null) || return 1
    onvif_action=inspect
    [ "$actual" = "$(onvif_arguments)" ]
}

onvif_discovery_owned() {
    discovery_pid="$1"; discovery_time="$2"
    case "$discovery_pid:$discovery_time" in *[!0-9:]*|:*) return 1;; esac
    [ "$discovery_pid" -gt 1 ] && [ -n "$discovery_time" ] || return 1
    [ "$(start_time "$discovery_pid")" = "$discovery_time" ] || return 1
    [ "$("$BB" readlink "$PROC/$discovery_pid/exe" 2>/dev/null)" = "$DISCOVERY" ] || return 1
    actual=$("$BB" tr '\000' '\n' < "$PROC/$discovery_pid/cmdline" 2>/dev/null) || return 1
    expected=$(printf '%s\n' "$DISCOVERY" --interface wlan0 --xaddr "http://$onvif_address:$ONVIF_PORT/" --uuid "$onvif_uuid")
    [ "$actual" = "$expected" ]
}

onvif_read_state() {
    [ -d "$ONVIF_STATE" ] && [ ! -L "$ONVIF_STATE" ] && regular "$ONVIF_STATE/owned" || return 1
    read -r server_pid server_time discovery_pid discovery_time onvif_address onvif_uuid extra < "$ONVIF_STATE/owned"
    [ -z "$extra" ] && valid_ipv4 "$onvif_address" || return 1
    case "$onvif_uuid" in ''|*[!0-9a-f-]*) return 1;; esac
    [ "${#onvif_uuid}" = 36 ] || return 1
    # Explicit direct mode owns no discovery process. Both fields must be zero.
    if [ "$discovery_pid" = 0 ] || [ "$discovery_time" = 0 ]; then
        [ "$discovery_pid:$discovery_time" = 0:0 ] || return 1
    fi
}

onvif_running() {
    onvif_read_state && onvif_owned "$server_pid" "$server_time" || return 1
    [ "$discovery_pid:$discovery_time" = 0:0 ] || onvif_discovery_owned "$discovery_pid" "$discovery_time"
}

onvif_discovery_running() {
    onvif_read_state && [ "$discovery_pid:$discovery_time" != 0:0 ] && \
        onvif_discovery_owned "$discovery_pid" "$discovery_time"
}
