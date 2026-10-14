#!/bin/sh
# Dedicated manual Fullhan pilot. These constants are not environment overrides.
ROOT="/mnt/LSCamoflash-fullhan"
CARD_MOUNT="/mnt"
STATE="/tmp/lscamoflash-fullhan"
CPUINFO="/proc/cpuinfo"
MOUNTS="/proc/mounts"
MEMINFO="/proc/meminfo"
UPTIME="/proc/uptime"
PROC="/proc"
STOCK="/usr/bin/dgiot"
STOCK_SHA="ef9545b2f4fce419d71dadf7723a9cb010500c994a87a325a8c325b51648c8b2"
PORT="8080"
HTTP_BIND="$PORT"
BB="$ROOT/bin/busybox"

fail() { printf '%s\n' "$1" >&2; return 1; }
regular() { [ -f "$1" ] && [ ! -L "$1" ]; }
root_user() { [ "$("$BB" id -u)" = 0 ]; }
identity() {
    "$BB" awk -F: 'tolower($1) ~ /^[[:space:]]*hardware[[:space:]]*$/ {
        gsub(/^[[:space:]]+|[[:space:]]+$/, "", $2); if (tolower($2)=="fh8626v100") good=1
    } END {exit !good}' "$CPUINFO" || return 1
    regular "$STOCK" || return 1
    stock_sum=$("$BB" sha256sum "$STOCK") || return 1
    [ "${stock_sum%% *}" = "$STOCK_SHA" ]
}
trusted_mount() {
    [ "$ROOT" = "$CARD_MOUNT/LSCamoflash-fullhan" ] || return 1
    for directory in /mnt "$ROOT" "$ROOT/bin" "$ROOT/www" "$ROOT/www/cgi-bin"; do
        [ -d "$directory" ] && [ ! -L "$directory" ] || return 1
    done
    magic=$("$BB" stat -f -c %t "$CARD_MOUNT") || return 1
    [ "$magic" = 4d44 ] || return 1
    visible=$("$BB" stat -c %d "$CARD_MOUNT") || return 1
    case "$visible" in ''|*[!0-9]*) return 1;; esac
    visible_major=$(( (visible >> 8) & 4095 ))
    visible_minor=$(( (visible & 255) | ((visible >> 12) & 1048320) ))
    matching=0
    writable=0
    while read -r device destination filesystem options rest; do
        [ "$destination" = "$CARD_MOUNT" ] || continue
        case "$filesystem" in vfat|fat|msdos) ;; *) continue;; esac
        [ "$device" = /dev/mmcblk0p1 ] && [ -b "$device" ] || continue
        pair=$("$BB" stat -c %t:%T "$device") || continue
        case "$pair" in ''|*[!0-9a-fA-F:]*|*:*:*) continue;; esac
        major=${pair%%:*}; minor=${pair#*:}
        [ -n "$major" ] && [ -n "$minor" ] && [ "$major" != "$pair" ] || continue
        [ "$((0x$major))" = "$visible_major" ] && [ "$((0x$minor))" = "$visible_minor" ] || continue
        matching=$((matching + 1))
        case ",$options," in *,rw,*) writable=1;; esac
    done < "$MOUNTS"
    [ "$matching" = 1 ] && [ "$writable" = 1 ]
}
verify_payload() {
    for path in $("$BB" find "$ROOT" -mindepth 1); do
        [ ! -L "$path" ] || return 1
        relative=${path#"$ROOT/"}
        if [ -d "$path" ]; then
            case "$relative" in bin|www|www/cgi-bin) ;; *) return 1;; esac
        else
            regular "$path" || return 1
            case "$relative" in start.sh|stop.sh|common.sh|bin/busybox|www/index.html|www/dashboard.js|www/cgi-bin/status.cgi|manifest.json|SHA256SUMS|README.md|LICENSE.MIT|COPYING.BusyBox|httpd.conf|startup.log) ;; *) return 1;; esac
        fi
    done
    (cd "$ROOT" && "$BB" sha256sum -c SHA256SUMS >/dev/null 2>&1)
}
auth_features() {
    # In BusyBox, AUTH_MD5 depends on BASIC_AUTH. Probe a public empty string;
    # this performs no socket operation and never handles a real credential.
    probe=$("$BB" httpd -m '' 2>/dev/null) || return 1
    printf '%s\n' "$probe" | "$BB" awk 'BEGIN {good=0} {
        n=split($0,a,"\\$")
        if(n==4 && a[1]=="" && a[2]=="1" && a[3]~/^[A-Za-z0-9.\/]+$/ && length(a[3])<=8 && a[4]~/^[A-Za-z0-9.\/]+$/ && length(a[4])==22)good=1
    } END {exit !good}'
}
auth_config() {
    regular "$ROOT/httpd.conf" && [ -s "$ROOT/httpd.conf" ] || return 1
    "$BB" awk '
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
        size=$("$BB" stat -c %s "$ROOT/startup.log") || return 1
        [ "$size" -le 65000 ] || return 0
    fi
    printf '%s\n' "$1" >> "$ROOT/startup.log"
}
start_time() {
    "$BB" sed 's/^.*) //' "$PROC/$1/stat" 2>/dev/null | "$BB" awk '{if($20~/^[0-9]+$/)print $20}'
}
owned_http() {
    pid="$1"; expected_time="$2"
    case "$pid:$expected_time" in *[!0-9:]*|:*) return 1;; esac
    [ "$pid" -gt 1 ] && [ -n "$expected_time" ] || return 1
    [ "$("$BB" readlink "$PROC/$pid/exe" 2>/dev/null)" = "$BB" ] || return 1
    [ "$(start_time "$pid")" = "$expected_time" ] || return 1
    "$BB" tr '\000' '\n' < "$PROC/$pid/cmdline" 2>/dev/null | "$BB" awk -v bb="$BB" -v root="$ROOT" -v bind="$HTTP_BIND" '
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
    "$BB" awk -v value="$1" 'BEGIN {
        if(split(value,a,".")!=4)exit 1
        for(i=1;i<=4;i++)if(a[i]!~/^[0-9]+$/ || length(a[i])>3 || a[i]+0>255)exit 1
        if(a[1]+0==0 || a[1]+0==127 || a[1]+0>=224)exit 1
    }'
}
valid_host() {
    "$BB" awk -v host="$1" 'BEGIN {
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
    candidates=$("$BB" ip -4 addr show 2>/dev/null | "$BB" awk '$1=="inet" {split($2,a,"/");if(a[1]!~/^127[.]/ && !seen[a[1]]++)print a[1]}') || return 1
    count=0; address=""
    for candidate in $candidates; do
        valid_ipv4 "$candidate" || return 1
        count=$((count+1)); address=$candidate
    done
    [ "$count" = 1 ] || return 1
    printf '%s\n' "$address"
}
