#!/bin/sh
# Optional, read-only post-init samples. Bootstrap owns the marker/init gate.
# Never source camera configuration or record argv, Wi-Fi names, or credentials.
hack="$1"
[ -n "$hack" ] && [ -d "$hack" ] && [ ! -L "$hack" ] || exit 0
busybox_hack="$hack/bin/busybox"
[ -x "$busybox_hack" ] || exit 0
proc_root=/proc
sys_root=/sys
tmp_root=/tmp
wpa_cli=/usr/bin/wpa_cli
log_dir="$hack/var/log"
[ -d "$log_dir" ] && [ ! -L "$hack/var" ] && [ ! -L "$log_dir" ] || exit 0
log_file="$log_dir/handoff.log"
previous_file="$log_dir/handoff.previous.log"
for candidate in "$log_file" "$previous_file"; do
	[ ! -L "$candidate" ] && { [ ! -e "$candidate" ] || [ -f "$candidate" ]; } || exit 0
done

tool() { "$busybox_hack" "$@"; }

if [ -f "$log_file" ]; then
	tool mv -f "$log_file" "$previous_file" || exit 0
fi
: > "$log_file" || exit 0
exec >> "$log_file" 2>/dev/null

sample_processes()
{
	process_count=0
	for process_dir in "$proc_root"/[0-9]*; do
		process_pid=${process_dir##*/}
		case "$process_pid" in ''|*[!0-9]*) continue ;; esac
		IFS= read -r process_comm < "$process_dir/comm" || continue
		case "$process_comm" in
			anyka_ipc|anyka_ipc_patched|anyka_ipc_patch|daemon|wpa_supplicant|udhcpc) ;;
			*) continue ;;
		esac
		process_ppid=$(tool awk '$1 == "PPid:" && $2 ~ /^[0-9]+$/ { print $2; exit }' "$process_dir/status")
		case "$process_ppid" in ''|*[!0-9]*) continue ;; esac
		printf 'process pid=%s ppid=%s comm=%s\n' "$process_pid" "$process_ppid" "$process_comm"
		process_count=$((process_count + 1))
		[ "$process_count" -lt 64 ] || break
	done
}

sample_network()
{
	interface_state=""
	IFS= read -r interface_state < "$sys_root/class/net/wlan0/operstate" || interface_state=""
	case "$interface_state" in
		up|down|unknown|dormant|notpresent|lowerlayerdown|testing) printf 'wlan0 operstate=%s\n' "$interface_state" ;;
		*) printf 'wlan0 operstate=unavailable\n' ;;
	esac
	# Drop the interface header (including HWaddr), IPv6 and unrelated text.
	tool timeout -k 1 2 "$busybox_hack" ifconfig wlan0 | tool awk '
		/HWaddr|ether / { next }
		/^[ \t]*(inet addr:[0-9]|inet [0-9]|UP |RX packets[: ]|TX packets[: ]|RX bytes[: ]|TX bytes[: ])/ {
			if (++lines <= 12) print substr($0, 1, 512)
		}'
	printf 'routes destination gateway mask flags metric ref use interface\n'
	tool timeout -k 1 2 "$busybox_hack" route -n | tool awk '
		NF == 8 && $1 ~ /^[0-9.]+$/ && $2 ~ /^[0-9.]+$/ && $3 ~ /^[0-9.]+$/ &&
		$4 ~ /^[A-Z!]+$/ && $5 ~ /^[0-9]+$/ && $6 ~ /^[0-9]+$/ && $7 ~ /^[0-9]+$/ &&
		$8 ~ /^(wlan[0-9]+|eth[0-9]+|lo)$/ { if (++lines <= 20) print }'
	if [ -x "$wpa_cli" ]; then
		LD_LIBRARY_PATH=/lib:/usr/lib tool timeout -k 1 2 "$wpa_cli" -iwlan0 status | tool awk -F= '
			NF == 2 && $1 == "wpa_state" && $2 ~ /^[A-Z_]+$/ && length($2) <= 64 && !seen[$1]++ { print }
			NF == 2 && $1 == "ip_address" && $2 ~ /^[0-9.]+$/ && length($2) <= 15 && !seen[$1]++ { print }
			NF == 2 && $1 == "key_mgmt" && $2 ~ /^[A-Za-z0-9_+\/-]+$/ && length($2) <= 64 && !seen[$1]++ { print }'
	else
		printf 'wpa_status=unavailable\n'
	fi
}

sample_handoff_state()
{
	for marker in _ht_ap_mode.conf _ak39_factory.ini _ht_get_log.conf setup.lock anyka_ipc.lock _ak39_startlock.ini services.run; do
		marker_exists=0
		[ ! -e "$tmp_root/$marker" ] && [ ! -L "$tmp_root/$marker" ] || marker_exists=1
		printf 'marker name=%s exists=%s\n' "$marker" "$marker_exists"
	done
	# Keep only the handoff mounts and technical source/type/access fields.
	# Do not copy unrelated mount paths or arbitrary mount option values.
	tool awk '
		$2 == "/mnt" || $2 == "/tmp/sd" || $2 == "/bin" || $2 == "/sbin" ||
		$2 == "/usr/bin/anyka_ipc" || $2 == "/etc/config/_ht_hw_settings.ini" {
			source="other"; type="other"; access="unknown"
			if ($1 ~ /^\/dev\/(root|mtdblock[0-9]+|mmcblk[0-9]+(p[0-9]+)?|loop[0-9]+)$/ || $1 ~ /^(tmpfs|rootfs|none)$/) source=$1
			if ($3 ~ /^(tmpfs|rootfs|vfat|fat|msdos|squashfs|jffs2|ext[234])$/) type=$3
			if ($4 ~ /(^|,)rw(,|$)/) access="rw"
			else if ($4 ~ /(^|,)ro(,|$)/) access="ro"
			if (++lines <= 32) printf "mount source=%s target=%s type=%s access=%s\n",source,$2,type,access
		}' "$proc_root/mounts"
}

elapsed=0
for interval in 0 5 10 15 30; do
	[ "$interval" -eq 0 ] || tool sleep "$interval"
	elapsed=$((elapsed + interval))
	uptime_value=$(tool awk '$1 ~ /^[0-9]+([.][0-9]+)?$/ { print $1; exit }' "$proc_root/uptime")
	printf '\nsample nominal_seconds=%s uptime=%s\n' "$elapsed" "${uptime_value:-unavailable}"
	sample_handoff_state
	sample_processes
	sample_network
done
printf '\nhandoff samples complete\n'
exit 0
