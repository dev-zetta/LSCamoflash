#!/bin/sh
# Called by the native entry with the verified card root, then stock arguments.
boot_root="$1"
shift
[ "$boot_root" = /mnt ] || exit 2
# Ash has opened its own script stream. Release the inherited verified FD so
# background services do not keep the original /mnt mount pinned indefinitely.
case "$0" in
	/proc/self/fd/*)
		bootstrap_fd=${0##*/}
		case "$bootstrap_fd" in ''|*[!0-9]*) exit 2 ;; esac
		eval "exec $bootstrap_fd<&-"
		;;
esac

# Export variables for init script
export hack="/tmp/sd/HACK"
export hack_conf="$hack/etc/hack.conf"
export hack_custom_conf="$hack/etc/hack_custom.conf"
export anyka_checksums_conf="$hack/etc/anyka_checksums.conf"
export commands_conf="$hack/etc/commands.conf"

# Custom scripts
custom_pre_init="/tmp/sd/CUSTOM/pre_init.sh"
custom_pre_init_async="/tmp/sd/CUSTOM/pre_init_custom.sh"
export custom_pre_services="/tmp/sd/CUSTOM/pre_services.sh"
export custom_pre_services_async="/tmp/sd/CUSTOM/pre_services_async.sh"
export custom_pre_services_once="/tmp/sd/CUSTOM/pre_services_once.sh"
export custom_pre_services_once_async="/tmp/sd/CUSTOM/pre_services_once_async.sh"

# SD device and path
sd_dev="/dev/mmcblk0p2"
sd_path="/tmp/sd"

# Logging
hack_log="/tmp/hostapd.log"
hack_err="/tmp/hostapd.err"

# Hostapd and config
hostapd="$boot_root/hostapd.real"
hostapd_real="/tmp/hostapd.real"
hostapd_conf="$boot_root/_ht_ap_mode.conf"

# Init script path
init="$hack/sbin/init.sh"

# Update script path
update="$hack/sbin/update.sh"

# Reboot flag
reboot_flag="/tmp/hostapd.reboot"
reboot_file="/tmp/sd/hostapd.reboot"

# Copy shadow and passwd files and clean them in case they were edited in windows
for i in shadow passwd; do
	[ -f "./$i" ] && cp ./$i /etc/config/$i >/dev/null 2>&1 && dos2unix /etc/config/$i
done

# Get anyka_ipc checksum
anyka_checksum_line=$(md5sum /usr/bin/anyka_ipc) || exit 1
export anyka_md5=$(printf '%s\n' "$anyka_checksum_line" | awk '{print $1}')

# Get device mac
export device_mac=`ifconfig wlan0 | grep HWaddr | awk '{print $5}'`

# Set device uid
export device_uid=`echo $device_mac | sha256sum | cut -d " " -f1`

if [ -x "$hostapd" -a -f "$hostapd_conf" -a "$1" != "" -a "$2" = "-B" ]; then
	# Start real hostapd, when config has ssid
	hostapd_ssid=`cat $hostapd_conf | grep "^ssid"`

	if [ "$hostapd_ssid" = "" ]; then
		cp $hostapd $hostapd_real
		$hostapd_real "$1" "$2"
	fi
else
	# Prefer the existing two-partition layout. A single FAT card with HACK/
	# can instead be bound at /tmp/sd; the stock unmount of /mnt then leaves
	# our runtime available. Never continue on a failed mount or bare tmpfs.
	mkdir -p "$sd_path" || exit 1
	sd_mount=$(awk -v path="$sd_path" '$2 == path { row=$0 } END { print row }' /proc/mounts)
	if [ -n "$sd_mount" ]; then
		printf '%s\n' "$sd_mount" | awk '
			$1 ~ /^\/dev\/mmcblk[0-9]+(p[0-9]+)?$/ &&
			($3 == "vfat" || $3 == "fat" || $3 == "msdos") &&
			$4 ~ /(^|,)rw(,|$)/ { valid=1 } END { exit !valid }' || exit 1
	elif [ -b "$sd_dev" ]; then
		mount -t vfat -o rw "$sd_dev" "$sd_path" || exit 1
	elif [ -f "$boot_root/HACK/etc/hack.conf" ]; then
		mount --bind "$boot_root" "$sd_path" || exit 1
	else
		echo "LSCamoflash: no runtime on partition 2 or the boot card" >&2
		exit 1
	fi
	[ -f "$hack_conf" ] && [ -x "$init" ] || exit 1

	# Leave AP mode before the normal vendor runtime starts. The .125 ATBM
	# driver does not revisit WIFI_MODE after this synchronous boot hook.
	rm -f /tmp/_ht_ap_mode.conf
	killall udhcpd
	ifconfig wlan0 0.0.0.0
	case "$anyka_md5" in
		7c2a124cdd607ebef63fb66d063b6a87)
			# Native entry execs BusyBox: this process is no longer hostapd,
			# which the vendor's station reload explicitly kills by name.
			/usr/sbin/wifi_driver_atbm6132c.sh sta || exit 1
			;;
	esac

	# Apply staged updates before any runtime or custom hook can use a mixed
	# tree. Stock startup has not loaded our configuration or command paths.
	# Keep these settings in a subshell; init loads its own configuration.
	if [ -x "$update" ]; then
		(
			. "$hack_conf" || exit 1
			if [ -n "$hack_custom_conf" ] && [ -f "$hack_custom_conf" ]; then
				. "$hack_custom_conf" || exit 1
			fi
			export busybox_firmware="$sys_bin/busybox"
			export busybox_hack="$sd_bin/busybox"
			. "$commands_conf" || exit 1
			[ -n "$sd_update" ] && [ -n "$sd_log" ] || exit 1
			if [ -d "$sd_update" ]; then
				$mkdir -p "$sd_log" || exit 1
				"$update" || {
					echo "LSCamoflash: staged update failed; see $sd_log/update.log" >&2
					exit 1
				}
			fi
		) || exit 1
	fi
	# Network update checks remain in services.sh after normal initialization.

	# Execute pre_init_async.sh
	[ -n "$custom_pre_init_async" -a -x "$custom_pre_init_async" ] && $custom_pre_init_async &
	[ -n "$custom_pre_init" -a -x "$custom_pre_init" ] && $custom_pre_init

	# Check for reboot file and move it to reboot flag
	[ -f "$reboot_file" ] && mv $reboot_file $reboot_flag

	# Check for reboot flag
	if [ -f $reboot_flag ]; then
		# Reboot
		rm -f $reboot_flag
		reboot
	else
		# Run init script
		"$init" >"$hack_log" 2>"$hack_err"
	fi
fi
