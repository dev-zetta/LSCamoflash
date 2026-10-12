#!/bin/sh
echo -n "LSCamoflash network script is starting up at " && date

# Check, whether we were called from hostapd script and load configs
[ -n "$hack" -a -n "$hack_conf" -a -f "$hack_conf" ] && . $hack_conf && echo "Configuration loaded from: $hack_conf" || exit 1
[ -n "$hack_custom_conf" ] && . $hack_custom_conf && echo "Custom configuration override loaded from: $hack_custom_conf"

# Redefine variables for next scripts (in case of /mnt is unmounted)
export hack="$sd_path/HACK"
export hack_conf="$hack/etc/hack.conf"
export hack_custom_conf="$hack/etc/hack_custom.conf"
export commands_conf="$hack/etc/commands.conf"

# Define busyboxes
export busybox_hack="$sd_bin/busybox"
export busybox_firmware="$sys_bin/busybox"

# Load commands variables
[ -n "$commands_conf" ] && . $commands_conf && echo "Command variables loaded from: $commands_conf" || exit 1

# Check wifi configuration override requirements
if [ "$wifi_config_override" = "1" ]; then
	wifi_reset_override=0

	[ -n "$wifi_driver" ] || wifi_reset_override=1
	[ -n "$wifi_ssid" ] || wifi_reset_override=1

    if [ "$wifi_reset_override" = "1" ]; then
		wifi_config_override=0
	fi
fi

network_mode="tuya"
wpa_supplicant="$sys_usr_bin/wpa_supplicant"
wpa_cli="$sys_usr_bin/wpa_cli"

write_network_state()
{
	# Publish a complete marker before init reads it; an empty new file must not
	# be mistaken for an invalid state while its writer is being scheduled.
	state_part="$network_file.part.$$"
	printf '%s\n' "$1" > "$state_part" && $mv -f "$state_part" "$network_file" || exit 1
}

network_failed()
{
	echo "$1" >&2
	[ -z "${wpa_pid:-}" ] || $kill "$wpa_pid" >/dev/null 2>&1 || true
	write_network_state failed
	exit 1
}

wifi_associated()
{
	LD_LIBRARY_PATH="/lib:/usr/lib" "$wpa_cli" -p /var/run/wpa_supplicant -i wlan0 status 2>/dev/null | $grep "^wpa_state=COMPLETED$" >/dev/null 2>&1
}

wait_for_wifi()
{
	wpa_wait=0
	while [ "$wpa_wait" -lt 30 ]; do
		wifi_associated && return 0
		$sleep 1
		wpa_wait=$((wpa_wait + 1))
	done
	return 1
}

stop_network_clients()
{
	for i in wpa_supplicant udhcpc; do
		proc=$(pgrep -f "$i" || true)
		[ -z "$proc" ] || $kill -KILL $proc
	done
}

configure_network()
{
	# Factory mode must not start the camera application on an unassociated link.
	# Keep the existing override behavior for other modes after the bounded wait.
	if ! wait_for_wifi && [ "$local_rtsp_only" = "1" ]; then
		network_failed "Factory RTSP Wi-Fi association failed after 30 attempts"
	fi
	if [ "$wifi_use_dhcp" = "1" -o "$wifi_ip_address" = "" ]; then
		network_mode="dhcp"
		$ifconfig lo up
		$ifconfig wlan0 0.0.0.0 up
		$udhcpc -x hostname:$(echo "$system_hostname" | $cut -d . -f1) \
		--interface=wlan0 --now --pidfile=/var/run/udhcpc-wlan0.pid \
		--script="$sd_sbin/udhcpc-hook.sh" > "$sd_log/udhcpc.log" 2>&1 &
	else
		network_mode="manual"
		[ -n "$wifi_ip_address" -a -n "$wifi_netmask" -a -n "$wifi_broadcast" ] && $ifconfig wlan0 $wifi_ip_address netmask $wifi_netmask broadcast $wifi_broadcast
		[ -n "$wifi_ip_address" -a -n "$wifi_netmask" ] && $ifconfig wlan0 $wifi_ip_address netmask $wifi_netmask
		[ -n "$wifi_ip_address" -a -n "$wifi_broadcast" ] && $ifconfig wlan0 $wifi_ip_address broadcast $wifi_broadcast
		[ -n "$wifi_ip_address" ] && $ifconfig wlan0 $wifi_ip_address netmask $wifi_netmask broadcast $wifi_broadcast
		[ -n "$wifi_gateway" ] && $route add default gw $wifi_gateway
		echo -n "" > "$sys_config/resolv.conf"
		[ -n "$wifi_domainname" ] && echo "domainname $wifi_domainname" >> "$sys_config/resolv.conf"
		[ -n "$wifi_nameserver" ] && echo "nameserver $wifi_nameserver" >> "$sys_config/resolv.conf"
	fi
}

# Wifi configuration
if [ "$wifi_config_override" = "1" ]; then
	echo "Wifi configuration override requested"
	echo "ctrl_interface=/var/run/wpa_supplicant" > "$sys_temp/wpa_custom.conf"
	echo "network={" >> "$sys_temp/wpa_custom.conf"
	echo "    ssid=\"$wifi_ssid\"" >> "$sys_temp/wpa_custom.conf"
	echo "    scan_ssid=$wifi_scan_ssid" >> "$sys_temp/wpa_custom.conf"
	echo "    key_mgmt=$wifi_key_mgmt" >> "$sys_temp/wpa_custom.conf"
	echo "    pairwise=$wifi_pairwise" >> "$sys_temp/wpa_custom.conf"
	echo "    group=$wifi_group" >> "$sys_temp/wpa_custom.conf"
	echo "    psk=\"$wifi_psk\"" >> "$sys_temp/wpa_custom.conf"
	echo "}" >> "$sys_temp/wpa_custom.conf"
	
   	# Disable wifi scripts
   	for i in `ls -1 $sys_usr_sbin/station_connect.sh $sys_usr_sbin/wifi_*`; do 
        mounted=`$cat /proc/mounts | $grep "$i" | $grep "$sd_bin/exit.sh" >/dev/null 2>&1 && echo 1 || echo 0`
        [ "$mounted" = "1" ] || mount --bind $sd_sbin/exit.sh $i
   	done
	
    # Copy wpa_supplicant to a safe execution position
   	[ -f "$sd_bin/wifi_sup" ] || $cp -f $sys_usr_bin/wpa_supplicant $sd_bin/wifi_sup
    [ -f "$sd_bin/wifi_cli" ] || $cp -f $sys_usr_bin/wpa_cli $sd_bin/wifi_cli
	
	wpa_supplicant="$sd_bin/wifi_sup"
    wpa_cli="$sd_bin/wifi_cli"

	# Disable wifi and networking tools
	for i in $sys_usr_bin/wpa_supplicant $sys_usr_bin/wpa_cli; do 
        mounted=`$cat /proc/mounts | $grep "$i" | $grep "$sd_bin/exit.sh" >/dev/null 2>&1 && echo 1 || echo 0`
		[ "$mounted" = "1" ] || mount --bind $sd_sbin/exit.sh $i
	done
	
	stop_network_clients

	LD_LIBRARY_PATH="/lib:/usr/lib" "$wpa_supplicant" -iwlan0 -D"$wifi_driver" -c "$sys_temp/wpa_custom.conf" > "$sd_log/wpa_supplicant.log" 2>&1 &
	wpa_pid=$!
	configure_network
elif [ "$local_rtsp_only" = "1" ] && [ "$anyka_md5" = "7c2a124cdd607ebef63fb66d063b6a87" ]; then
	# This firmware normally reconstructs its paired WPA file from the encrypted
	# Tuya database. Factory mode bypasses that step, so only reuse a file that
	# stock firmware has already created in RAM; never copy or print credentials.
	paired_wpa_conf="$sys_temp/wpa_supplicant.conf"
	[ -f "$paired_wpa_conf" ] && [ -r "$paired_wpa_conf" ] && [ -s "$paired_wpa_conf" ] ||
		network_failed "Factory RTSP requires wifi_config_override=1 with custom Wi-Fi settings when no stock RAM WPA configuration exists"
	[ -x "$wpa_supplicant" ] && [ -x "$wpa_cli" ] ||
		network_failed "Factory RTSP requires the stock WPA supplicant and control client"
	stop_network_clients
	LD_LIBRARY_PATH="/lib:/usr/lib" "$wpa_supplicant" -iwlan0 -Dnl80211 -c "$paired_wpa_conf" >/dev/null 2>&1 &
	wpa_pid=$!
	wifi_use_dhcp=1
	configure_network
fi

write_network_state "$network_mode"

if [ "$network_mode" != "tuya" ]; then
	while true; do
		$sleep 60

		# Check whether wpa_supplicant reports a completed connection.
		LD_LIBRARY_PATH="/lib:/usr/lib" $wpa_cli -p /var/run/wpa_supplicant -i wlan0 status 2>/dev/null | $grep "wpa_state=COMPLETED" >/dev/null 2>&1
		if [ $? -ne 0 ]; then
			echo "wpa_supplicant not connected; trying reassociate..."
			LD_LIBRARY_PATH="/lib:/usr/lib" $wpa_cli -p /var/run/wpa_supplicant -i wlan0 reassociate >/dev/null 2>&1 || true
			$sleep 5
			LD_LIBRARY_PATH="/lib:/usr/lib" $wpa_cli -p /var/run/wpa_supplicant -i wlan0 status 2>/dev/null | $grep "wpa_state=COMPLETED" >/dev/null 2>&1
			if [ $? -ne 0 ]; then
				echo "wpa_supplicant not responding or failed to connect, restarting network..."
				$sd_sbin/network.sh &
				exit 0
			fi
		fi

		if [ "$network_mode" = "dhcp" ]; then
			# Prefer checking udhcpc pidfile (we start udhcpc with --pidfile)
			if [ -f /var/run/udhcpc-wlan0.pid ]; then
				udhcpc_pid=`$cat /var/run/udhcpc-wlan0.pid 2>/dev/null || echo ""`
				if [ -z "$udhcpc_pid" ] || ! $kill -0 "$udhcpc_pid" 2>/dev/null; then
					echo "udhcpc not running (pidfile stale), restarting network..."
					$sd_sbin/network.sh &
					exit 0
				fi
			else
				# fallback to previous ps-based check
				$ps w | $grep udhcpc | $grep -v grep | $awk '{print $1}' >/dev/null 2>&1 || {
					echo "udhcpc not running, restarting network..."
					$sd_sbin/network.sh &
					exit 0
				}
			fi
		fi
	done
fi
