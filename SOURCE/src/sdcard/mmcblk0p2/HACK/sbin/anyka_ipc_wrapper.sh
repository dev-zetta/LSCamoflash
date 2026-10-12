#!/bin/sh

# This is called by the firmware watchdog through the bind-mounted bootstrap.
# Keep the camera process in the foreground so an exit can be restarted normally.
export hack="${hack:-/tmp/sd/HACK}"

# Opt-in stock logging also enables a small launch trace. Keep exec in this
# process so the firmware watchdog still sees the stock application's PID.
wrapper_diag_log=""
wrapper_phase()
{
	[ -z "$wrapper_diag_log" ] || printf 'pid=%s phase=%s\n' "$$" "$1" >> "$wrapper_diag_log" 2>/dev/null
	return 0
}
if [ -f "${sys_temp:-/tmp}/_ht_get_log.conf" ]; then
	wrapper_diag_log="$hack/var/log/wrapper-status.log"
	wrapper_diag_previous="$hack/var/log/wrapper-status.previous.log"
	if [ ! -d "$hack/var/log" ] || [ -L "$hack/var/log" ] ||
		[ -L "$wrapper_diag_log" ] || [ -L "$wrapper_diag_previous" ] ||
		{ [ -e "$wrapper_diag_log" ] && [ ! -f "$wrapper_diag_log" ]; } ||
		{ [ -e "$wrapper_diag_previous" ] && [ ! -f "$wrapper_diag_previous" ]; }; then
		wrapper_diag_log=""
	elif { [ ! -f "$wrapper_diag_log" ] || "$hack/bin/busybox" mv -f "$wrapper_diag_log" "$wrapper_diag_previous"; } &&
		: > "$wrapper_diag_log"; then
		wrapper_phase entry
		trap 'wrapper_result=$?; trap - EXIT; wrapper_phase "exit:$wrapper_result"; exit "$wrapper_result"' EXIT
	else
		wrapper_diag_log=""
	fi
fi
[ -f "$hack/etc/hack.conf" ] || exit 1
. "$hack/etc/hack.conf" || exit 1
if [ -f "$hack/etc/hack_custom.conf" ]; then
	. "$hack/etc/hack_custom.conf" || exit 1
fi
export busybox_hack="$sd_bin/busybox"
export busybox_firmware="$sys_bin/busybox"
[ -x "$busybox_hack" -a -x "$busybox_firmware" ] || exit 1
. "$hack/etc/commands.conf" || exit 1
wrapper_phase configuration-loaded

stock_md5_line=$("$busybox_hack" md5sum "$sd_bin/anyka_ipc") || exit 1
stock_md5=$(printf '%s\n' "$stock_md5_line" | $awk '{print $1}')
anyka_md5="${1:-$stock_md5}"
case "$anyka_md5" in
	''|*[!a-fA-F0-9]*) echo "Invalid stock anyka_ipc checksum" >&2; exit 1 ;;
esac
[ "${#anyka_md5}" -eq 32 ] || exit 1

anyka_ipc_bin="$sd_bin/anyka_ipc"
anyka_ipc_lib="$sd_lib"
force_factory="$FORCE_AK39_FACTORY_ON_ORIGIN"

# This revision has no validated replacement or IPS patch. Recheck on every
# watchdog restart, since the wrapper reloads configuration independently of init.
stock_binary_only=0
if [ "$anyka_md5" = "7c2a124cdd607ebef63fb66d063b6a87" -o "$stock_md5" = "7c2a124cdd607ebef63fb66d063b6a87" ]; then
	if [ "$anyka_md5" != "$stock_md5" ]; then
		echo "Stock binary MD5 does not match the requested 3007325.5 profile" >&2
		exit 1
	fi
	stock_sha256_line=$("$busybox_hack" sha256sum "$anyka_ipc_bin") || exit 1
	stock_sha256=$(printf '%s\n' "$stock_sha256_line" | $awk '{print $1}')
	if [ "$stock_sha256" != "d710cfe53a9e0098e4271db4fff2fc485e38acdaf78d965accaf2e516980534d" ]; then
		echo "Stock 3007325.5 binary does not match the supported firmware" >&2
		exit 1
	fi
	stock_binary_only=1
	if [ "$FORCE_AK39_FACTORY_ON_ORIGIN" = "1" -o "$FORCE_AK39_FACTORY_ON_PATCHED" = "1" -o \
		"$FORCE_AK39_FACTORY_ON_STATIC_PATCHED" = "1" -o "$FORCE_AK39_FACTORY_ON_STATIC" = "1" ]; then
		echo "AK39 manufacturing mode is unsupported for 3007325.5; use local_rtsp_only=1 instead" >&2
		exit 1
	fi
fi
wrapper_phase identity-verified

# Factory RTSP deliberately uses the stock firmware even if a dynamic or static
# patch is installed. It also works without an IPS patch on some firmware builds.
if [ "$local_rtsp_only" != "1" -a "$stock_binary_only" != "1" ]; then
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
	wrapper_phase setup-locked
	$sleep 60
	exit 2
fi
[ ! -f "$sys_temp/_ak39_startlock.ini" ] || wrapper_phase start-locked
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
ap_marker="$sys_temp/_ht_ap_mode.conf"
ap_owned="$sys_temp/anyka_rtsp_ap.owned"
if [ "$stock_binary_only" = "1" ]; then
	# On this build AK39 mode is a manufacturing test, not the RTSP branch.
	# Remove our obsolete marker, but refuse to override another owner's mode.
	if [ -f "$factory_owned" ]; then
		$rm -f "$factory_marker" "$factory_owned" || exit 1
	fi
	if [ -e "$factory_marker" ]; then
		echo "Conflicting AK39 manufacturing marker; refusing to start 3007325.5" >&2
		exit 1
	fi
	if [ "$local_rtsp_only" = "1" ]; then
		if [ ! -e "$ap_marker" ]; then
			$touch "$ap_owned" || exit 1
			if ! $touch "$ap_marker"; then
				$rm -f "$ap_owned"
				exit 1
			fi
		fi
	elif [ -f "$ap_owned" ]; then
		$rm -f "$ap_marker" "$ap_owned" || exit 1
	fi
elif [ "$local_rtsp_only" = "1" -o "$force_factory" = "1" ]; then
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
	wrapper_phase exec-local-rtsp
	exec "$busybox_hack" sh "$sd_sbin/anyka_rtsp.sh" "$anyka_md5"
fi
wrapper_phase exec-stock
exec "$anyka_ipc_bin"
