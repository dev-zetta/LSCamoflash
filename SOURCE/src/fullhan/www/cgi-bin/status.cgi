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
        printf "{\"total_kB\":%.0f,\"free_kB\":%.0f,\"available_kB\":%.0f,\"used_kB\":%.0f,\"available_reported\":%s}",total,free,available,total-available,reported?"true":"false"
    }' "$MEMINFO") || response_error "503 Service unavailable" "Memory counters unavailable"
cpu=$("$BB" awk 'NR==1 {for(i=1;i<=3;i++)if($i!~/^[0-9]+([.][0-9]+)?$/)$i=0; printf "{\"load_1m\":%s,\"load_5m\":%s,\"load_15m\":%s}",$1,$2,$3}' "$LOADAVG" 2>/dev/null)
[ -n "$cpu" ] || cpu='{"load_1m":0,"load_5m":0,"load_15m":0}'
storage='{"mounted":false,"total_kB":0,"used_kB":0,"available_kB":0}'
if trusted_mount; then
    storage=$("$BB" df -k "$CARD_MOUNT" 2>/dev/null | "$BB" awk '$1=="/dev/mmcblk0p1" && $2~/^[0-9]+$/ && $3~/^[0-9]+$/ && $4~/^[0-9]+$/ {printf "{\"mounted\":true,\"total_kB\":%.0f,\"used_kB\":%.0f,\"available_kB\":%.0f}",$2,$3,$4}')
    [ -n "$storage" ] || storage='{"mounted":false,"total_kB":0,"used_kB":0,"available_kB":0}'
fi
rtsp=false
"$BB" netstat -tln 2>/dev/null | "$BB" awk '$1=="tcp" && $4~/[:]8554$/ && $6=="LISTEN" {ok=1} END {exit !ok}' && rtsp=true
stock_app=false; stock_rss=0
stock_pids=$("$BB" pidof dgiot 2>/dev/null)
for stock_pid in $stock_pids; do
    case "$stock_pid" in *[!0-9]*) continue;; esac
    process="$PROC/$stock_pid"
    [ "$("$BB" readlink "$process/exe" 2>/dev/null)" = "$STOCK" ] || continue
    stock_app=true
    stock_rss=$("$BB" awk '$1=="VmRSS:" && $2~/^[0-9]+$/ {print $2}' "$process/status" 2>/dev/null)
    break
done
management_rss=0
if regular "$STATE/pid"; then
    read -r pid timestamp extra < "$STATE/pid"
    if [ -z "$extra" ] && owned_http "$pid" "$timestamp"; then
        management_rss=$("$BB" awk '$1=="VmRSS:" && $2~/^[0-9]+$/ {print $2}' "$PROC/$pid/status" 2>/dev/null)
    fi
fi
onvif_available=false; onvif_running=false; discovery_running=false
if regular "$ROOT/bin/onvif_srvd" && regular "$ROOT/onvif-common.sh"; then
    onvif_available=true
    # Optional isolated service owns only its own process state.
    . "$ROOT/onvif-common.sh"
    if command -v onvif_running >/dev/null 2>&1 && onvif_running; then onvif_running=true; fi
    if command -v onvif_discovery_running >/dev/null 2>&1 && onvif_discovery_running; then discovery_running=true; fi
fi
printf 'Content-Type: application/json\r\nCache-Control: no-store\r\nX-Content-Type-Options: nosniff\r\n\r\n'
[ "$REQUEST_METHOD" != HEAD ] || exit 0
printf '{"backend":"fullhan-stock","model":"LSC SZB22705","firmware":"FW7.6.23","ip":"%s","uptime_seconds":%s,"memory":%s,"cpu":%s,"storage":%s,"services":{"stock_app":%s,"rtsp":%s,"onvif":%s},"onvif":{"available":%s,"url":"http://%s:5000/","authentication_required":true,"discovery_running":%s},"diagnostics":{"management_rss_kB":%s,"stock_app_rss_kB":%s},"streams":{"main":"rtsp://%s:8554/main","sub":"rtsp://%s:8554/sub","codec":"H264","verified_video_only":true,"audio":"unverified"},"stock_app_managed":false,"settings_write":false,"network_write":false,"ptz":false,"reboot":false,"firmware_update":false}\n' "$ip" "${uptime:-0}" "$memory" "$cpu" "$storage" "$stock_app" "$rtsp" "$onvif_running" "$onvif_available" "$ip" "$discovery_running" "${management_rss:-0}" "${stock_rss:-0}" "$ip" "$ip"
