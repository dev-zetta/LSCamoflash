#!/bin/sh
# Isolated, explicitly provisioned SSH. No firmware/password/network changes.
ROOT="/mnt/sdcard/LSCamoflash-yyos-ssh"
CARD_MOUNT="/mnt/sdcard"
MMC="/dev/mmcblk0p1"
RAM="/run"
STATE="$RAM/lscamoflash-yyos-ssh"
PROC="/proc"
CPUINFO="$PROC/cpuinfo"
MOUNTS="$PROC/mounts"
UPTIME="$PROC/uptime"
STOCK="/appfs/bin/yy_cam"
STOCK_SHA="d76d632f41453f53d9d117582fc47073934f5e6ec9a9b7a0ebb1dd3824f6cba7"
BB="$ROOT/bin/busybox"
DB="$ROOT/bin/dropbear"
PORT="2222"
WAIT_SECONDS=120
PAYLOAD_FILES="common.sh start.sh stop.sh README.md bin/busybox bin/dropbear LICENSE.MIT COPYING.BusyBox COPYING.Dropbear manifest.json"
tool() { "$BB" timeout -k 1 5 "$BB" "$@"; }
fail() { printf '%s\n' "$1" >&2; return 1; }
regular() { [ -f "$1" ] && [ ! -L "$1" ]; }
no_symlinks() {
    case "$1" in /*) ;; *) return 1;; esac
    case "$1" in *[!A-Za-z0-9_./-]*|*/../*|*/./*) return 1;; esac
    current=; old_ifs=$IFS; IFS=/
    for component in $1; do
        [ -n "$component" ] || continue
        current=$current/$component
        [ ! -L "$current" ] || { IFS=$old_ifs; return 1; }
    done
    IFS=$old_ifs
}
identity() {
    [ "$(tool id -u)" = 0 ] && regular "$STOCK" || return 1
    tool awk -F: '/^Hardware[ \t]*:/ {gsub(/^[ \t]+|[ \t]+$/,"",$2); if($2=="AK3918AV130")good++} END {exit good!=1}' "$CPUINFO" || return 1
    value=$(tool sha256sum "$STOCK") || return 1
    [ "${value%% *}" = "$STOCK_SHA" ]
}
trusted_mount() {
    [ "$ROOT" = "$CARD_MOUNT/LSCamoflash-yyos-ssh" ] || return 1
    for path in "$CARD_MOUNT" "$ROOT" "$ROOT/bin" "$MMC" "$RAM"; do no_symlinks "$path" || return 1; done
    [ "$(tool stat -f -c %t "$CARD_MOUNT")" = 4d44 ] || return 1
    visible=$(tool stat -c %d "$CARD_MOUNT") || return 1
    case "$visible" in ''|*[!0-9]*) return 1;; esac
    count=0; writable=0
    while read -r source destination filesystem options rest; do
        [ "$destination" = "$CARD_MOUNT" ] && [ "$source" = "$MMC" ] && [ "$filesystem" = vfat ] || continue
        [ -b "$source" ] && [ ! -L "$source" ] || continue # FIXTURE_BLOCK_CHECK
        pair=$(tool stat -c %t:%T "$source") || return 1
        case "$pair" in ''|*[!0-9a-fA-F:]*|*:*:*) return 1;; esac
        major=${pair%:*}; minor=${pair#*:}
        [ -n "$major" ] && [ -n "$minor" ] && [ "${#major}" -le 5 ] && [ "${#minor}" -le 5 ] || return 1
        major=$((0x$major)); minor=$((0x$minor))
        [ "$visible" = "$(((minor & 255) | ((major & 4095) << 8) | ((minor & 1048320) << 12)))" ] || continue
        count=$((count+1)); case ",$options," in *,rw,*) writable=1;; esac
    done < "$MOUNTS"
    [ "$count" = 1 ] && [ "$writable" = 1 ] || return 1
    [ "$(tool stat -f -c %t "$RAM")" = 1021994 ] || return 1
    # Dropbear checks every authorized_keys ancestor, including /run and /.
    for path in / "$RAM"; do
        info=$(tool stat -c '%u %g %a' "$path") || return 1
        set -- $info
        [ "$#" = 3 ] && [ "$1" = 0 ] && [ "$2" = 0 ] || return 1
        case "$3" in [0-7][0-7][0-7]) ;; *) return 1;; esac
        [ "$((0$3 & 022))" = 0 ] || return 1
    done
    tool awk -v root="$RAM" '$2==root && $3=="tmpfs" {n++; if("," $4 "," ~ /,rw,/)rw++} END {exit n!=1 || rw!=1}' "$MOUNTS"
}
verify_payload() {
    regular "$ROOT/SHA256SUMS" || return 1
    for path in $PAYLOAD_FILES; do regular "$ROOT/$path" || return 1; done
    paths=$(tool find "$ROOT" -mindepth 1) || return 1
    for path in $paths; do
        [ ! -L "$path" ] || return 1
        relative=${path#"$ROOT/"}
        if [ -d "$path" ]; then [ "$relative" = bin ] || return 1
        else
            regular "$path" || return 1
            case " $PAYLOAD_FILES SHA256SUMS authorized_keys dropbear_ed25519_host_key ssh.enabled startup.log " in *" $relative "*) ;; *) return 1;; esac
        fi
    done
    tool awk -v files="$PAYLOAD_FILES" 'BEGIN {n=split(files,a," ");for(i=1;i<=n;i++)ok[a[i]]=1}
        {if(split($0,a,"  ")!=2 || length(a[1])!=64 || a[1]~/[^0-9a-f]/ || !ok[a[2]] || seen[a[2]]++)bad=1;count++}
        END {exit bad || count!=n}' "$ROOT/SHA256SUMS" || return 1
    (cd "$ROOT" && tool sha256sum -c SHA256SUMS >/dev/null 2>&1)
}
key_inputs() {
    regular "$ROOT/ssh.enabled" && [ "$(tool stat -c %s "$ROOT/ssh.enabled")" = 8 ] &&
        [ "$(tool cat "$ROOT/ssh.enabled")" = enabled ] || return 1
    regular "$ROOT/authorized_keys" && [ "$(tool stat -c %s "$ROOT/authorized_keys")" -le 512 ] || return 1
    key=$(tool awk 'NR!=1 || $0~/[^ -~]/ || NF<2 || $1!="ssh-ed25519" || length($2)!=68 || $2~/[^A-Za-z0-9+\/]/ {bad=1}
        NR==1 {key=$2} END {if(bad || NR!=1)exit 1;print key}' "$ROOT/authorized_keys") || return 1
    numbers=$(printf '%s' "$key" | tool base64 -d | tool od -An -v -tu1) || return 1
    printf '%s\n' "$numbers" | tool awk 'BEGIN {split("0 0 0 11 115 115 104 45 101 100 50 53 53 49 57 0 0 0 32",h," ")}
        {for(i=1;i<=NF;i++){n++;if(n<=19 && $i!=h[n])bad=1}} END {exit bad || n!=51}' || return 1
    regular "$ROOT/dropbear_ed25519_host_key" && [ "$(tool stat -c %s "$ROOT/dropbear_ed25519_host_key")" = 83 ] || return 1
    tool od -An -v -tu1 -N19 "$ROOT/dropbear_ed25519_host_key" | tool awk 'BEGIN {split("0 0 0 11 115 115 104 45 101 100 50 53 53 49 57 0 0 0 64",h," ")}
        {for(i=1;i<=NF;i++){n++;if($i!=h[n])bad=1}} END {exit bad || n!=19}'
}
private_ipv4() {
    tool awk -v ip="$1" 'BEGIN {if(split(ip,a,".")!=4)exit 1;for(i=1;i<=4;i++)if(a[i]!~/^[0-9]+$/ || length(a[i])>3 || a[i]+0>255)exit 1;
        exit !((a[1]+0==10)||(a[1]+0==172 && a[2]+0>=16 && a[2]+0<=31)||(a[1]+0==192 && a[2]+0==168))}'
}
read_ip() {
    values=$(tool ip -4 addr show dev wlan0 2>/dev/null | tool awk '$1=="inet"{split($2,a,"/");if(!seen[a[1]]++)print a[1]}') || return 1
    set -- $values
    [ "$#" = 1 ] && private_ipv4 "$1" || return 1
    printf '%s\n' "$1"
}
port_listening() {
    tool netstat -tln 2>/dev/null | tool awk -v port="$PORT" '$1=="tcp" && $4~":" port "$" && $6=="LISTEN"{yes=1} END{exit !yes}'
}
start_time() { tool sed 's/^.*) //' "$PROC/$1/stat" 2>/dev/null | tool awk '$20~/^[0-9]+$/{print $20}'; }
owned_ssh() {
    candidate=$1; stamp=$2; bind=$3
    case "$candidate:$stamp" in ''|*[!0-9:]*|:*) return 1;; esac
    [ "$candidate" -gt 1 ] && [ -n "$stamp" ] && private_ipv4 "$bind" || return 1
    [ "$(tool readlink "$PROC/$candidate/exe" 2>/dev/null)" = "$DB" ] && [ "$(start_time "$candidate")" = "$stamp" ] || return 1
    expected="$DB -F -s -j -k -D $STATE -r $STATE/dropbear_ed25519_host_key -P $STATE/dropbear.pid -p $bind:$PORT -I 600 -K 30 -T 3"
    tool tr '\000' '\n' < "$PROC/$candidate/cmdline" 2>/dev/null | tool awk -v expected="$expected" '
        BEGIN{n=split(expected,a," ")} {if($0!=a[NR])bad=1} END{exit bad || NR!=n}'
}
log_status() {
    if [ -e "$ROOT/startup.log" ] || [ -L "$ROOT/startup.log" ]; then
        regular "$ROOT/startup.log" || return 1
        [ "$(tool stat -c %s "$ROOT/startup.log")" -le 65000 ] || return 0
    fi
    printf '%s\n' "$1" >> "$ROOT/startup.log"
}
remove_state() {
    for file in owner dropbear.pid authorized_keys dropbear_ed25519_host_key; do
        [ ! -e "$STATE/$file" ] || tool rm "$STATE/$file" || return 1
    done
    tool rmdir "$STATE"
}
no_direct_children() {
    parent=$1; scanned=0
    for path in "$PROC"/[0-9]*; do
        [ -d "$path" ] || continue
        scanned=$((scanned+1)); [ "$scanned" -le 256 ] || return 1
        value=$(tool sed 's/^.*) //' "$path/stat" 2>/dev/null | tool awk '$2~/^[0-9]+$/{print $2}') || value=
        if [ -z "$value" ]; then [ ! -d "$path" ] || return 1
        else [ "$value" != "$parent" ] || return 1; fi
    done
}
no_remaining_dropbear() {
    scanned=0
    for path in "$PROC"/[0-9]*; do
        [ -d "$path" ] || continue
        scanned=$((scanned+1)); [ "$scanned" -le 256 ] || return 1
        value=$(tool readlink "$path/exe" 2>/dev/null) || value=
        [ "$value" != "$DB" ] || return 1
    done
}
