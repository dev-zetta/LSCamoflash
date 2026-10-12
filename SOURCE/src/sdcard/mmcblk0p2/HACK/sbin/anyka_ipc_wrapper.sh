#!/bin/sh

# This is called by the firmware watchdog through the bind-mounted bootstrap.
# Keep the camera process in the foreground so an exit can be restarted normally.
export hack="${hack:-/tmp/sd/HACK}"
[ -f "$hack/etc/hack.conf" ] || exit 1
. "$hack/etc/hack.conf" || exit 1
if [ -f "$hack/etc/hack_custom.conf" ]; then
	. "$hack/etc/hack_custom.conf" || exit 1
fi
export busybox_hack="$sd_bin/busybox"
export busybox_firmware="$sys_bin/busybox"
[ -x "$busybox_hack" -a -x "$busybox_firmware" ] || exit 1
. "$hack/etc/commands.conf" || exit 1

anyka_md5="${1:-$($md5sum "$sd_bin/anyka_ipc" | $awk '{print $1}')}"
case "$anyka_md5" in
	''|*[!a-fA-F0-9]*) echo "Invalid stock anyka_ipc checksum" >&2; exit 1 ;;
esac
[ "${#anyka_md5}" -eq 32 ] || exit 1

anyka_ipc_bin="$sd_bin/anyka_ipc"
anyka_ipc_lib="$sd_lib"
force_factory="$FORCE_AK39_FACTORY_ON_ORIGIN"

# Factory RTSP deliberately uses the stock firmware even if a dynamic or static
# patch is installed. It also works without an IPS patch on some firmware builds.
if [ "$local_rtsp_only" != "1" ]; then
	if [ -x "$sd_bin/anyka_ipc_patched" ]; then
		anyka_ipc_bin="$sd_bin/anyka_ipc_patched"
		force_factory="$FORCE_AK39_FACTORY_ON_PATCHED"
	elif [ -x "$sd_patch/$anyka_md5/bin/anyka_ipc_patched" ]; then
		anyka_ipc_bin="$sd_patch/$anyka_md5/bin/anyka_ipc_patched"
		anyka_ipc_lib="$sd_patch/$anyka_md5/lib"
		force_factory="$FORCE_AK39_FACTORY_ON_STATIC_PATCHED"
	elif [ -x "$sd_patch/$anyka_md5/bin/anyka_ipc" ]; then
		anyka_ipc_bin="$sd_patch/$anyka_md5/bin/anyka_ipc"
		anyka_ipc_lib="$sd_patch/$anyka_md5/lib"
		force_factory="$FORCE_AK39_FACTORY_ON_STATIC"
	fi
fi

[ -x "$anyka_ipc_bin" ] || { echo "Missing executable $anyka_ipc_bin" >&2; exit 1; }
if [ -f "$sys_temp/anyka_ipc.lock" -o -f "$sys_temp/setup.lock" ]; then
	$sleep 60
	exit 2
fi
while [ -f "$sys_temp/_ak39_startlock.ini" ]; do
	$sleep 3
done

# Stop the camera instance started before the wrapper was bind-mounted, or left
# by a previous mode. Exclude this wrapper if the firmware reports it by name.
for ipc_pid in $($pidof anyka_ipc anyka_ipc_patched 2>/dev/null); do
	case "$ipc_pid" in
		''|*[!0-9]*) continue ;;
	esac
	[ "$ipc_pid" = "$$" ] || $kill -KILL "$ipc_pid" >/dev/null 2>&1
done

# Keep the existing service stop/start controls informed of the actual executable.
printf '%s\n' "$anyka_ipc_bin" > "$sys_temp/anyka_ipc_wrapper.cmd" || exit 1
export LD_LIBRARY_PATH="/lib:/usr/lib:$anyka_ipc_lib"

# Remove factory mode on a configuration change only when this wrapper created
# the marker. A marker supplied by the firmware or user remains theirs to clear.
factory_marker="$sys_temp/_ak39_factory.ini"
factory_owned="$sys_temp/anyka_factory.owned"
if [ "$local_rtsp_only" = "1" -o "$force_factory" = "1" ]; then
	if [ ! -e "$factory_marker" ]; then
		$touch "$factory_owned" || exit 1
		if ! $touch "$factory_marker"; then
			$rm -f "$factory_owned"
			exit 1
		fi
	fi
elif [ -f "$factory_owned" ]; then
	$rm -f "$factory_marker" "$factory_owned" || exit 1
fi

# Never change motor calibration here: it belongs to the camera's own hardware
# settings, including on devices with unknown firmware checksums.
$rm -f "$sys_config"/logseq* "$sys_config/log_seq_stat" >/dev/null 2>&1 || true

case "$FORCE_STATE_LED_OFF" in
	''|0|*[!0-9]*) ;;
	*)
		if command -v state_led.sh >/dev/null 2>&1; then
			($sleep "$FORCE_STATE_LED_OFF" && state_led.sh off) &
		fi
		;;
esac

if [ "$local_rtsp_only" = "1" ]; then
	exec "$busybox_hack" sh "$sd_sbin/anyka_rtsp.sh"
fi
exec "$anyka_ipc_bin"
