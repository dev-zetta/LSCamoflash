#!/bin/sh

# Called by anyka_ipc_wrapper.sh after loading configuration and checking locks.
# A LAN stream needs no default gateway. Do not leave a start lock behind or
# detach from the firmware watchdog: it must be able to restart the stock server.
[ -n "$hack" -a -n "$sd_bin" -a -n "$sys_temp" ] || exit 1
[ -x "$sd_bin/anyka_ipc" ] || { echo "Missing stock anyka_ipc" >&2; exit 1; }
[ -x "$busybox_hack" ] || exit 1
stock_md5_line=$("$busybox_hack" md5sum "$sd_bin/anyka_ipc") || exit 1
stock_md5=$(printf '%s\n' "$stock_md5_line" | $awk '{print $1}')
if [ "$stock_md5" = "7c2a124cdd607ebef63fb66d063b6a87" -o "$1" = "7c2a124cdd607ebef63fb66d063b6a87" ]; then
	[ "$stock_md5" = "$1" -a "$local_rtsp_only" = "1" ] || exit 1
	stock_sha256_line=$("$busybox_hack" sha256sum "$sd_bin/anyka_ipc") || exit 1
	stock_sha256=$(printf '%s\n' "$stock_sha256_line" | $awk '{print $1}')
	[ "$stock_sha256" = "d710cfe53a9e0098e4271db4fff2fc485e38acdaf78d965accaf2e516980534d" ] || exit 1
	if [ ! -f "$sys_temp/_ht_ap_mode.conf" -o -e "$sys_temp/_ak39_factory.ini" ]; then
		echo "3007325.5 RTSP mode was not prepared safely by the wrapper" >&2
		exit 1
	fi
else
	[ -f "$sys_temp/_ak39_factory.ini" ] || { echo "Factory mode was not prepared by the wrapper" >&2; exit 1; }
fi
export LD_LIBRARY_PATH="/lib:/usr/lib:$sd_lib"
echo "Starting stock anyka_ipc in local RTSP mode"
exec "$sd_bin/anyka_ipc"
