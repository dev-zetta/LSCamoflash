#!/bin/sh

root="/tmp/sd/HACK"

. ./common.cgi

LC_ALL=C
export LC_ALL

# Kernel counters and unavailable devices must still produce JSON numbers.
uint()
{
    awk -v value="$1" 'BEGIN {if (value ~ /^[0-9]+$/ && value+0 <= 9007199254740991) printf "%.0f", value+0; else printf "0"}'
}
number()
{
    awk -v value="$1" 'BEGIN {if (value ~ /^[0-9]+([.][0-9]+)?$/ && value+0 <= 9007199254740991) printf "%.2f", value+0; else printf "0"}'
}

# A covered tmpfs row can precede the FAT row. Match the mounted directory's
# actual device number to the MMC block node, rather than trusting row order.
visible_mmc_device()
{
    local candidate_path="$1" candidate_device mounted_number raw_number major minor device_number
    mounted_number=$(stat -c %D "$candidate_path" 2>/dev/null) || return 1
    case "$mounted_number" in ''|*[!0-9a-fA-F]*) return 1;; esac
    for candidate_device in $(awk -v path="$candidate_path" '
        $2 == path && $1 ~ /^\/dev\/mmcblk[0-9]+(p[0-9]+)?$/ &&
        ($3 == "vfat" || $3 == "fat" || $3 == "msdos") {print $1}' /proc/mounts); do
        [ "$(stat -c %F "$candidate_device" 2>/dev/null)" = "block special file" ] || continue
        raw_number=$(stat -c %t:%T "$candidate_device" 2>/dev/null) || continue
        case "$raw_number" in ''|*[!0-9a-fA-F:]*|*:*:*) continue;; esac
        major=${raw_number%%:*}
        minor=${raw_number#*:}
        [ -n "$major" ] && [ -n "$minor" ] && [ "$major" != "$raw_number" ] || continue
        device_number=$(( (0x$major & 4095) << 8 | (0x$minor & 255) | (0x$minor & 4294967040) << 12 | (0x$major & 4294963200) << 32 ))
        if [ "$((0x$mounted_number))" = "$device_number" ]; then
            printf '%s\n' "$candidate_device"
            return 0
        fi
    done
    return 1
}

device_bytes()
{
    local value
    [ "$(stat -c %F "$1" 2>/dev/null)" = "block special file" ] || { printf '0'; return; }
    value=$(uint "$(blockdev --getsize64 "$1" 2>/dev/null)")
    if [ "$value" = 0 ]; then
        value=$(uint "$(fdisk -l "$1" 2>/dev/null | awk -v device="$1:" '$1 == "Disk" && $2 == device {for (i=3; i<NF; i++) if ($(i+1) == "bytes") {print $i; exit}}')")
    fi
    printf '%s' "$value"
}

device_used()
{
    local candidate_path
    for candidate_path in $(awk -v device="$1" '$1 == device {print $2}' /proc/mounts); do
        if [ "$(visible_mmc_device "$candidate_path")" = "$1" ]; then
            uint "$(df -Pk "$candidate_path" 2>/dev/null | awk 'NR == 2 {printf "%.0f", $3*1024}')"
            return
        fi
    done
    printf '0'
}

MEM_TOTAL=$(uint "$(awk '/^MemTotal:/ {print $2; exit}' /proc/meminfo 2>/dev/null)")
MEM_FREE=$(uint "$(awk '/^MemFree:/ {print $2; exit}' /proc/meminfo 2>/dev/null)")
MEM_AVAILABLE_RAW=$(awk '/^MemAvailable:/ {print $2; exit}' /proc/meminfo 2>/dev/null)
MEM_AVAILABLE=$(uint "$MEM_AVAILABLE_RAW")
MEM_AVAILABLE_REPORTED=$(awk -v value="$MEM_AVAILABLE_RAW" 'BEGIN {print (value ~ /^[0-9]+$/ && value+0 <= 9007199254740991) ? "true" : "false"}')
MEM_BUFFERS=$(uint "$(awk '/^Buffers:/ {print $2; exit}' /proc/meminfo 2>/dev/null)")
MEM_CACHED=$(uint "$(awk '/^Cached:/ {print $2; exit}' /proc/meminfo 2>/dev/null)")
MEM_RECLAIMABLE=$(uint "$(awk '/^SReclaimable:/ {print $2; exit}' /proc/meminfo 2>/dev/null)")
MEM_SHARED=$(uint "$(awk '/^Shmem:/ {print $2; exit}' /proc/meminfo 2>/dev/null)")
CPU_MODEL=$(awk -F':[[:space:]]*' '/^(model name|Processor)[[:space:]]*:/ {print $2; exit}' /proc/cpuinfo 2>/dev/null)
CPU_CORES=$(uint "$(awk '/^processor[[:space:]]*:/ {count++} END {print count+0}' /proc/cpuinfo 2>/dev/null)")
UPTIME_SECONDS=$(uint "$(awk '{printf "%.0f", int($1); exit}' /proc/uptime 2>/dev/null)")
UPTIME_HUMAN=$(awk -v value="$UPTIME_SECONDS" 'BEGIN {printf "%d Tage, %02d:%02d:%02d", value/86400, (value%86400)/3600, (value%3600)/60, value%60}')
LOAD_1MIN=$(number "$(awk '{print $1; exit}' /proc/loadavg 2>/dev/null)")
LOAD_5MIN=$(number "$(awk '{print $2; exit}' /proc/loadavg 2>/dev/null)")
LOAD_15MIN=$(number "$(awk '{print $3; exit}' /proc/loadavg 2>/dev/null)")

CPU1=$(awk '/^cpu / {print $2, $3, $4, $5; exit}' /proc/stat 2>/dev/null)
sleep 1
CPU2=$(awk '/^cpu / {print $2, $3, $4, $5; exit}' /proc/stat 2>/dev/null)
CPU_USAGE=$(uint "$(awk -v first="$CPU1" -v second="$CPU2" 'BEGIN {
    split(first,a," "); split(second,b," "); total=0; idle=0;
    for (i=1;i<=4;i++) {if (a[i] !~ /^[0-9]+$/ || b[i] !~ /^[0-9]+$/ || b[i]<a[i]) {print 0; exit} total+=b[i]-a[i]}
    idle=b[4]-a[4]; if (total>0) printf "%.0f", int(100*(total-idle)/total); else print 0
}')")

SD_DEVICE=$(visible_mmc_device "${sd_path:-/tmp/sd}")
[ -n "$SD_DEVICE" ] || SD_DEVICE=$(visible_mmc_device "${sys_mnt:-/mnt}")
SD_PART1_SIZE=0
SD_PART2_SIZE=0
SD_PART1_USED=0
SD_PART2_USED=0
SD_CARD_SIZE=0
if [ -n "$SD_DEVICE" ]; then
    SD_CARD_DEVICE=$(printf '%s\n' "$SD_DEVICE" | sed 's/p[0-9][0-9]*$//')
    SD_CARD_SIZE=$(device_bytes "$SD_CARD_DEVICE")
    if [ "$SD_CARD_DEVICE" = "$SD_DEVICE" ]; then
        # Preserve the existing UI schema: the whole FAT volume is slot 1.
        SD_PART1_SIZE=$SD_CARD_SIZE
        SD_PART1_USED=$(device_used "$SD_DEVICE")
    else
        SD_PART1_SIZE=$(device_bytes "${SD_CARD_DEVICE}p1")
        SD_PART2_SIZE=$(device_bytes "${SD_CARD_DEVICE}p2")
        SD_PART1_USED=$(device_used "${SD_CARD_DEVICE}p1")
        SD_PART2_USED=$(device_used "${SD_CARD_DEVICE}p2")
    fi
fi
SD_CARD_USED=$((SD_PART1_USED + SD_PART2_USED))
[ "$SD_CARD_SIZE" != 0 ] || SD_CARD_SIZE=$((SD_PART1_SIZE + SD_PART2_SIZE))
SD_CARD_SIZE_GB=$(awk -v value="$SD_CARD_SIZE" 'BEGIN {printf "%.1f GiB", value/1073741824}')

send_header application/json
cat <<EOF
{
  "memory": {
    "total_kB": $MEM_TOTAL,
    "free_kB": $MEM_FREE,
    "available_kB": $MEM_AVAILABLE,
    "available_reported": $MEM_AVAILABLE_REPORTED,
    "buffers_kB": $MEM_BUFFERS,
    "cached_kB": $MEM_CACHED,
    "reclaimable_kB": $MEM_RECLAIMABLE,
    "shared_kB": $MEM_SHARED
  },
  "cpu": {
    "model": "$(printf '%s' "$CPU_MODEL" | tr -d '\000-\037' | sed 's/\\/\\\\/g; s/"/\\"/g')",
    "cores": $CPU_CORES,
    "usage_percent": $CPU_USAGE
  },
  "uptime": {
    "seconds": $UPTIME_SECONDS,
    "human_readable": "$UPTIME_HUMAN"
  },
  "load": {
    "min1": $LOAD_1MIN,
    "min5": $LOAD_5MIN,
    "min15": $LOAD_15MIN
  },
  "sdcard": {
    "size": $SD_CARD_SIZE,
    "used": $SD_CARD_USED,
    "size_gb": "$SD_CARD_SIZE_GB",
    "partition1": {
      "size": $SD_PART1_SIZE,
      "used": $SD_PART1_USED
    },
    "partition2": {
      "size": $SD_PART2_SIZE,
      "used": $SD_PART2_USED
    }
  }
}
EOF
