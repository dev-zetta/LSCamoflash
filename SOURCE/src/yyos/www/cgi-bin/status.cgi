#!/mnt/sdcard/LSCamoflash-yyos/bin/busybox sh
. /mnt/sdcard/LSCamoflash-yyos/common.sh || exit 1
response_error() {
    printf 'Status: %s\r\nContent-Type: application/json\r\nCache-Control: no-store\r\n\r\n{"error":"%s"}\n' "$1" "$2"
    exit 1
}
case "${REQUEST_METHOD:-}" in GET|HEAD) ;; *) response_error '405 Method not allowed' 'Read-only endpoint';; esac
valid_host "${HTTP_HOST:-}" || response_error '400 Bad request' 'Invalid host'
ip=$(read_ipv4) || response_error '503 Service unavailable' 'No unique local IPv4 address'
uptime=$(tool awk 'NR==1 {if($1~/^[0-9]+([.][0-9]+)?$/ && $1+0<=9007199254740991)printf "%.0f",int($1);else printf "0"}' "$UPTIME")
memory=$(tool awk '
    $1~/^(MemTotal:|MemFree:|MemAvailable:|Buffers:|Cached:|SReclaimable:|Shmem:)$/ && !seen[$1]++ {
        if($2~/^[0-9]+$/ && $2+0<=9007199254740991 && $3=="kB")v[$1]=$2+0
        if($1=="MemAvailable:" && $2~/^[0-9]+$/ && $2+0<=9007199254740991 && $3=="kB")reported=1
    } END {
        total=v["MemTotal:"]+0;free=v["MemFree:"]+0
        available=reported?v["MemAvailable:"]:free+v["Buffers:"]+v["Cached:"]+v["SReclaimable:"]-v["Shmem:"]
        if(available<0)available=0;if(available>total)available=total
        printf "{\"total_kB\":%.0f,\"free_kB\":%.0f,\"available_kB\":%.0f,\"used_kB\":%.0f,\"available_reported\":%s}",total,free,available,total-available,reported?"true":"false"
    }' "$MEMINFO") || response_error '503 Service unavailable' 'Memory counters unavailable'
cpu=$(tool awk 'NR==1 {for(i=1;i<=3;i++)if($i!~/^[0-9]+([.][0-9]+)?$/ || $i+0>9007199254740991)$i=0;printf "{\"load_1m\":%.2f,\"load_5m\":%.2f,\"load_15m\":%.2f}",$1,$2,$3}' "$LOADAVG" 2>/dev/null)
[ -n "$cpu" ] || cpu='{"load_1m":0,"load_5m":0,"load_15m":0}'
storage='{"mounted":false,"total_kB":0,"used_kB":0,"available_kB":0}'
if trusted_mount; then
    storage=$(tool df -k "$CARD_MOUNT" 2>/dev/null | tool awk -v device="$MMC" '$1==device && $2~/^[0-9]+$/ && $3~/^[0-9]+$/ && $4~/^[0-9]+$/ && $2+0<=9007199254740991 && $3+0<=9007199254740991 && $4+0<=9007199254740991 {printf "{\"mounted\":true,\"total_kB\":%.0f,\"used_kB\":%.0f,\"available_kB\":%.0f}",$2,$3,$4}')
    [ -n "$storage" ] || storage='{"mounted":false,"total_kB":0,"used_kB":0,"available_kB":0}'
fi
rtsp=false;onvif=false;stock_app=false;management=false;stock_rss=0;management_rss=0
port_listening 8554 && rtsp=true
port_listening 5000 && onvif=true
stock_pids=$(tool pidof yy_cam 2>/dev/null) || stock_pids=
for stock_pid in $stock_pids; do
    case "$stock_pid" in ''|*[!0-9]*) continue;; esac
    [ "$(tool readlink "$PROC/$stock_pid/exe" 2>/dev/null)" = "$STOCK" ] || continue
    stock_app=true
    stock_rss=$(tool awk '$1=="VmRSS:" && $2~/^[0-9]+$/ && $2+0<=9007199254740991 && $3=="kB" {print $2;exit}' "$PROC/$stock_pid/status" 2>/dev/null)
    break
done
if http_running; then
    management=true
    management_rss=$(tool awk '$1=="VmRSS:" && $2~/^[0-9]+$/ && $2+0<=9007199254740991 && $3=="kB" {print $2;exit}' "$PROC/$owner_pid/status" 2>/dev/null)
fi
printf 'Content-Type: application/json\r\nCache-Control: no-store\r\nX-Content-Type-Options: nosniff\r\n\r\n'
[ "$REQUEST_METHOD" != HEAD ] || exit 0
printf '{"backend":"yyos-stock","model":"LSC 3225722 / SZ F26312","firmware":"V14.1.5 experimental","ip":"%s","uptime_seconds":%s,"memory":%s,"cpu":%s,"storage":%s,"services":{"stock_app":%s,"management":%s,"native_rtsp_listening":%s,"native_onvif_listening":%s},"diagnostics":{"management_rss_kB":%s,"stock_app_rss_kB":%s},"streams":{"main_candidate":"rtsp://%s:8554/stream0","sub_candidate":"rtsp://%s:8554/stream1","verified":false,"audio":"unverified","authentication":"unverified"},"onvif":{"candidate_url":"http://%s:5000/onvif/device_service","verified":false,"authentication":"unverified"},"stock_app_managed":false,"settings_write":false,"network_write":false,"recordings":false,"ptz":false,"reboot":false,"firmware_update":false}\n' "$ip" "${uptime:-0}" "$memory" "$cpu" "$storage" "$stock_app" "$management" "$rtsp" "$onvif" "${management_rss:-0}" "${stock_rss:-0}" "$ip" "$ip" "$ip"
