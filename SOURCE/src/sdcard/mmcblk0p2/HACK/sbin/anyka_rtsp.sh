#!/bin/sh

# Called by anyka_ipc_wrapper.sh after loading configuration and checking locks.
# A LAN stream needs no default gateway. Do not leave a start lock behind or
# detach from the firmware watchdog: it must be able to restart the stock server.
[ -n "$hack" -a -n "$sd_bin" -a -n "$sys_temp" ] || exit 1
[ -x "$sd_bin/anyka_ipc" ] || { echo "Missing stock anyka_ipc" >&2; exit 1; }
[ -f "$sys_temp/_ak39_factory.ini" ] || { echo "Factory mode was not prepared by the wrapper" >&2; exit 1; }
export LD_LIBRARY_PATH="/lib:/usr/lib:$sd_lib"
echo "Starting stock anyka_ipc in local factory RTSP mode"
exec "$sd_bin/anyka_ipc"
