#!/bin/sh
# Dedicated YYOS read-only management profile. These constants are not environment overrides.
ROOT="/mnt/sdcard/LSCamoflash-yyos"
CARD_MOUNT="/mnt/sdcard"
MMC="/dev/mmcblk0p1"
STATE="/tmp/lscamoflash-yyos"
CPUINFO="/proc/cpuinfo"
MOUNTS="/proc/mounts"
MEMINFO="/proc/meminfo"
UPTIME="/proc/uptime"
LOADAVG="/proc/loadavg"
PROC="/proc"
STOCK="/appfs/bin/yy_cam"
STOCK_SHA="d76d632f41453f53d9d117582fc47073934f5e6ec9a9b7a0ebb1dd3824f6cba7"
PORT="8080"
HTTP_BIND="$PORT"
BB="$ROOT/bin/busybox"

# Individual observations are bounded; the persistent HTTP daemon is not timed.
tool() { "$BB" timeout -k 1 5 "$BB" "$@"; }

fail() { printf '%s\n' "$1" >&2; return 1; }
regular() { [ -f "$1" ] && [ ! -L "$1" ]; }
root_user() { [ "$(tool id -u)" = 0 ]; }
identity() {
    tool awk -F: 'tolower($1) ~ /^[[:space:]]*hardware[[:space:]]*$/ {
        gsub(/^[[:space:]]+|[[:space:]]+$/, "", $2); if (tolower($2)=="ak3918av130") good=1
    } END {exit !good}' "$CPUINFO" || return 1
    regular "$STOCK" || return 1
    stock_sum=$(tool sha256sum "$STOCK") || return 1
    [ "${stock_sum%% *}" = "$STOCK_SHA" ]
}
trusted_mount() {
    [ "$ROOT" = "$CARD_MOUNT/LSCamoflash-yyos" ] || return 1
    for directory in /mnt "$CARD_MOUNT" "$ROOT" "$ROOT/bin" "$ROOT/www" "$ROOT/www/cgi-bin"; do
        [ -d "$directory" ] && [ ! -L "$directory" ] || return 1
    done
    magic=$(tool stat -f -c %t "$CARD_MOUNT") || return 1
    [ "$magic" = 4d44 ] || return 1
    visible=$(tool stat -c %d "$CARD_MOUNT") || return 1
    case "$visible" in ''|*[!0-9]*) return 1;; esac
    visible_major=$(( (visible >> 8) & 4095 ))
    visible_minor=$(( (visible & 255) | ((visible >> 12) & 1048320) ))
    matching=0
    writable=0
    while read -r device destination filesystem options rest; do
        [ "$destination" = "$CARD_MOUNT" ] || continue
        case "$filesystem" in vfat|fat|msdos) ;; *) continue;; esac
        [ "$device" = "$MMC" ] && [ -b "$device" ] && [ ! -L "$device" ] || continue
        pair=$(tool stat -c %t:%T "$device") || continue
        case "$pair" in ''|*[!0-9a-fA-F:]*|*:*:*) continue;; esac
        major=${pair%%:*}; minor=${pair#*:}
        [ -n "$major" ] && [ -n "$minor" ] && [ "$major" != "$pair" ] || continue
        [ "$((0x$major))" = "$visible_major" ] && [ "$((0x$minor))" = "$visible_minor" ] || continue
        matching=$((matching + 1))
        case ",$options," in *,rw,*) writable=1;; esac
    done < "$MOUNTS"
    [ "$matching" = 1 ] && [ "$writable" = 1 ]
}
PAYLOAD_FILES="start.sh stop.sh common.sh README.md bin/busybox www/index.html www/dashboard.js www/dashboard.css www/cgi-bin/status.cgi LICENSE.MIT COPYING.BusyBox manifest.json"
verify_payload() {
    regular "$ROOT/SHA256SUMS" || return 1
    for relative in $PAYLOAD_FILES; do regular "$ROOT/$relative" || return 1; done
    paths=$(tool find "$ROOT" -mindepth 1) || return 1
    for path in $paths; do
        [ ! -L "$path" ] || return 1
        relative=${path#"$ROOT/"}
        if [ -d "$path" ]; then
            case "$relative" in bin|www|www/cgi-bin) ;; *) return 1;; esac
        else
            regular "$path" || return 1
            case " $PAYLOAD_FILES SHA256SUMS httpd.conf startup.log " in *" $relative "*) ;; *) return 1;; esac
        fi
    done
    tool awk -v files="$PAYLOAD_FILES" '
        BEGIN {expected=split(files,names," ");for(i=1;i<=expected;i++)allowed[names[i]]=1}
        {n=split($0,a,"  ");if(n!=2 || length(a[1])!=64 || a[1]~/[^0-9a-f]/ || !(a[2] in allowed) || seen[a[2]]++)bad=1;count++}
        END {exit bad || count!=expected}' "$ROOT/SHA256SUMS" || return 1
    (cd "$ROOT" && tool sha256sum -c SHA256SUMS >/dev/null 2>&1)
}

auth_features() {
    # In BusyBox, AUTH_MD5 depends on BASIC_AUTH. Probe a public empty string;
    # this performs no socket operation and never handles a real credential.
    probe=$(tool httpd -m '' 2>/dev/null) || return 1
    printf '%s\n' "$probe" | tool awk 'BEGIN {good=0} {
        n=split($0,a,"\\$")
        if(n==4 && a[1]=="" && a[2]=="1" && a[3]~/^[A-Za-z0-9.\/]+$/ && length(a[3])<=8 && a[4]~/^[A-Za-z0-9.\/]+$/ && length(a[4])==22)good=1
    } END {exit !good}'
}
auth_config() {
    regular "$ROOT/httpd.conf" && [ -s "$ROOT/httpd.conf" ] || return 1
    tool awk '
        /^[[:space:]]*#/ || /^[[:space:]]*$/ {next}
        $0=="I:index.html" {next}
        {
            n=split($0,a,":")
            if(n!=3 || a[1]!="/" || a[2]!~/^[A-Za-z0-9_.-]+$/ || length(a[2])>32) {bad=1;next}
            h=split(a[3],b,"\\$")
            if(h!=4 || b[1]!="" || b[2]!="1" || b[3]!~/^[A-Za-z0-9.\/]+$/ || length(b[3])>8 || b[4]!~/^[A-Za-z0-9.\/]+$/ || length(b[4])!=22) {bad=1;next}
            auth++
        } END {exit bad || auth!=1}' "$ROOT/httpd.conf"
}
log_status() {
    # Fixed startup/stop lines only; HTTP requests and CGI stderr are not logged.
    if [ -e "$ROOT/startup.log" ] || [ -L "$ROOT/startup.log" ]; then
        regular "$ROOT/startup.log" || return 1
        size=$(tool stat -c %s "$ROOT/startup.log") || return 1
        [ "$size" -le 65000 ] || return 0
    fi
    printf '%s\n' "$1" >> "$ROOT/startup.log"
}
start_time() {
    tool sed 's/^.*) //' "$PROC/$1/stat" 2>/dev/null | tool awk '{if($20~/^[0-9]+$/)print $20}'
}
owned_http() {
    pid="$1"; expected_time="$2"
    case "$pid:$expected_time" in *[!0-9:]*|:*) return 1;; esac
    [ "$pid" -gt 1 ] && [ -n "$expected_time" ] || return 1
    [ "$(tool readlink "$PROC/$pid/exe" 2>/dev/null)" = "$BB" ] || return 1
    [ "$(start_time "$pid")" = "$expected_time" ] || return 1
    tool tr '\000' '\n' < "$PROC/$pid/cmdline" 2>/dev/null | tool awk -v bb="$BB" -v root="$ROOT" -v bind="$HTTP_BIND" '
        NR==1 && $0!=bb {bad=1}
        NR==2 && $0!="httpd" {bad=1}
        NR==3 && $0!="-f" {bad=1}
        NR==4 && $0!="-c" {bad=1}
        NR==5 && $0!=root "/httpd.conf" {bad=1}
        NR==6 && $0!="-h" {bad=1}
        NR==7 && $0!=root "/www" {bad=1}
        NR==8 && $0!="-p" {bad=1}
        NR==9 && $0!=bind {bad=1}
        END {exit bad || NR!=9}'
}
valid_ipv4() {
    tool awk -v value="$1" 'BEGIN {
        if(split(value,a,".")!=4)exit 1
        for(i=1;i<=4;i++)if(a[i]!~/^[0-9]+$/ || length(a[i])>3 || a[i]+0>255)exit 1
        if(a[1]+0==0 || a[1]+0==127 || a[1]+0>=224)exit 1
    }'
}
valid_host() {
    tool awk -v host="$1" 'BEGIN {
        if(length(host)<1 || length(host)>259 || host~/[^A-Za-z0-9.:-]/)exit 1
        n=split(host,h,":"); if(n>2)exit 1
        if(n==2 && (h[2]!~/^[0-9]+$/ || h[2]+0<1 || h[2]+0>65535))exit 1
        if(length(h[1])<1 || length(h[1])>253)exit 1
        count=split(h[1],a,".")
        if(h[1]~/^[0-9.]+$/) {
            if(count!=4)exit 1
            for(i=1;i<=4;i++)if(a[i]!~/^[0-9]+$/ || length(a[i])>3 || a[i]+0>255)exit 1
        }
        for(i=1;i<=count;i++)if(length(a[i])<1 || length(a[i])>63 || a[i]!~/^[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?$/)exit 1
    }'
}
read_ipv4() {
    candidates=$(tool ip -4 addr show 2>/dev/null | tool awk '$1=="inet" {split($2,a,"/");if(a[1]!~/^127[.]/ && !seen[a[1]]++)print a[1]}') || return 1
    count=0; address=""
    for candidate in $candidates; do
        valid_ipv4 "$candidate" || return 1
        count=$((count+1)); address=$candidate
    done
    [ "$count" = 1 ] || return 1
    printf '%s\n' "$address"
}

port_listening() {
    tool netstat -tln 2>/dev/null | tool awk -v port="$1" '$1=="tcp" && $4 ~ ":" port "$" && $6=="LISTEN" {found=1} END {exit !found}'
}
http_running() {
    [ -d "$STATE" ] && [ ! -L "$STATE" ] && regular "$STATE/pid" || return 1
    read -r owner_pid owner_time extra < "$STATE/pid" || return 1
    [ -z "$extra" ] && owned_http "$owner_pid" "$owner_time"
}
