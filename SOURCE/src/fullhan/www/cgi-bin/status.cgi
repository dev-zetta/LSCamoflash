#!/mnt/LSCamoflash-fullhan/bin/busybox sh
. /mnt/LSCamoflash-fullhan/common.sh || exit 1
response_error() {
    printf 'Status: %s\r\nContent-Type: application/json\r\nCache-Control: no-store\r\n\r\n{"error":"%s"}\n' "$1" "$2"
    exit 1
}
case "$REQUEST_METHOD" in GET|HEAD) ;; *) response_error "405 Method not allowed" "Read-only endpoint";; esac
valid_host "${HTTP_HOST:-}" || response_error "400 Bad request" "Invalid host"
ip=$(read_ipv4) || response_error "503 Service unavailable" "No unique local IPv4 address"
uptime=$("$BB" awk 'NR==1 {if($1~/^[0-9]+([.][0-9]+)?$/ && $1+0<=9007199254740991)printf "%.0f",int($1);else printf "0"}' "$UPTIME")
memory=$("$BB" awk '
    $1~/^(MemTotal:|MemFree:|MemAvailable:|Buffers:|Cached:|SReclaimable:|Shmem:)$/ && !seen[$1]++ {
        if($2~/^[0-9]+$/ && $2+0<=9007199254740991 && $3=="kB")v[$1]=$2+0
        if($1=="MemAvailable:" && $2~/^[0-9]+$/ && $2+0<=9007199254740991 && $3=="kB")reported=1
    } END {
        total=v["MemTotal:"]+0; free=v["MemFree:"]+0
        available=reported?v["MemAvailable:"]:free+v["Buffers:"]+v["Cached:"]+v["SReclaimable:"]-v["Shmem:"]
        if(available<0)available=0; if(available>total)available=total
        printf "{\"total_kB\":%.0f,\"free_kB\":%.0f,\"available_kB\":%.0f,\"available_reported\":%s}",total,free,available,reported?"true":"false"
    }' "$MEMINFO") || response_error "503 Service unavailable" "Memory counters unavailable"
printf 'Content-Type: application/json\r\nCache-Control: no-store\r\nX-Content-Type-Options: nosniff\r\n\r\n'
[ "$REQUEST_METHOD" != HEAD ] || exit 0
printf '{"backend":"fullhan-stock","model":"LSC SZB22705","firmware":"FW7.6.23","ip":"%s","uptime_seconds":%s,"memory":%s,"streams":{"main":"rtsp://%s:8554/main","sub":"rtsp://%s:8554/sub","codec":"H264","verified_video_only":true,"audio":"unverified"},"stock_app_managed":false,"settings_write":false,"network_write":false,"ptz":false,"reboot":false,"firmware_update":false}\n' "$ip" "${uptime:-0}" "$memory" "$ip" "$ip"
