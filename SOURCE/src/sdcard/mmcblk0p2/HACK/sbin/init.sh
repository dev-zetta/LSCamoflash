#!/bin/sh
echo -n "LSCamoflash init script is starting up at " && date

# Issue #2 mitigation: Early cleanup of problematic flash files
# These may exist on /etc/config from previous failed boots and must be removed immediately
rm -f /etc/config/logseq* /etc/config/log_seq_stat >/dev/null 2>&1 || true

# Check, whether we were called from hostapd script and load configs
[ -n "$hack" -a -n "$hack_conf" -a -f "$hack_conf" ] && . $hack_conf && echo "Configuration loaded from: $hack_conf" || exit 1
[ -n "$hack_custom_conf" -a -f "$hack_custom_conf" ] && . "$hack_custom_conf" && echo "Custom configuration override loaded from: $hack_custom_conf"

# Redefine variables for next scripts (in case of /mnt is unmounted)
export hack="$sd_path/HACK"
export hack_conf="$hack/etc/hack.conf"
export hack_custom_conf="$hack/etc/hack_custom.conf"
export anyka_checksums_conf="$hack/etc/anyka_checksums.conf"
export commands_conf="$hack/etc/commands.conf"

# Define busyboxes
export busybox_hack="$sd_bin/busybox"
export busybox_firmware="$sys_bin/busybox"

# Setup lock
export setup_lock_file="/tmp/setup.lock"

# Load commands variables
[ -n "$commands_conf" ] && . $commands_conf && echo "Command variables loaded from: $commands_conf" || exit 1

# Load anyka checksums
[ -n "$anyka_checksums_conf" ] && . "$anyka_checksums_conf" && echo "Anyka checksums loaded from: $anyka_checksums_conf" || exit 1
# Updates preserve camera configuration, including checksum files from older
# releases. Keep the identity for this stock-only profile available there too.
indoor_ptz_3007325_5_6_2863_125_originl=${indoor_ptz_3007325_5_6_2863_125_originl:-7c2a124cdd607ebef63fb66d063b6a87}
indoor_ptz_3007325_5_6_2863_125_sha256=${indoor_ptz_3007325_5_6_2863_125_sha256:-d710cfe53a9e0098e4271db4fff2fc485e38acdaf78d965accaf2e516980534d}

# Repair Mode: Check for /tmp/sd/INJECT directory with recovery archives
if [ -d "$sd_inject" ]; then
	echo "Repair Mode: Found $sd_inject directory"
	
	# List of potential repair archives
	for archive in bin etc lib sbin usr var; do
		archive_file="$sd_inject/$archive.tar"
		log_file="$sd_inject/$archive.log"
		
		if [ -f "$archive_file" ]; then
			echo "Repair Mode: Processing $archive.tar..."
			
			# Create log file with timestamp
			date > "$log_file"
			echo "Extracting $archive.tar to /" >> "$log_file"
			
			# Extract archive to root filesystem (overwriting)
			$tar -xvf "$archive_file" -C / >> "$log_file" 2>&1
			extract_result=$?
			
			if [ $extract_result -eq 0 ]; then
				echo "Repair Mode: $archive.tar extracted successfully"
				# Delete archive after successful extraction
				$rm -f "$archive_file"
			else
				echo "Repair Mode: WARNING - Failed to extract $archive.tar (exit code: $extract_result)"
				echo "ERROR: Extraction failed with exit code $extract_result" >> "$log_file"
			fi
		fi
	done
	
	echo "Repair Mode: Completed"
fi

# Binding and setting up hostname config
if [ -n "$system_hostname" ]; then
        echo $system_hostname | $cut -d . -f1 > /tmp/hostname
        if [ -f "$sd_etc/hosts.online" ]; then
		$cp $sd_etc/hosts.online /tmp/hosts
	else
	        echo "127.0.0.1         localhost:localdomain           localhost" > /tmp/hosts
	fi
        echo "127.0.1.1         $system_hostname        $(echo $system_hostname | $cut -d . -f1)" >> /tmp/hosts
        $mount --bind /tmp/hostname /etc/sysconfig/HOSTNAME
        $mount --bind /tmp/hosts /etc/hosts
        $hostname $(echo $system_hostname | $cut -d . -f1)
fi

# Stop only this init's children on failure, including an outer timeout signal.
# Successful initialization leaves the network monitor and supervisor running.
network_pid=""
services_supervisor=""
finish_init()
{
	local init_result=$? init_child init_child_parent
	trap - EXIT HUP INT TERM
	if [ "$init_result" -ne 0 ]; then
		for init_child in "$services_supervisor" "$network_pid"; do
			case "$init_child" in ''|*[!0-9]*) continue;; esac
			init_child_parent=$("$busybox_hack" awk '$1 == "PPid:" {print $2}' "/proc/$init_child/status" 2>/dev/null)
			[ "$init_child_parent" = "$$" ] || continue
			if [ "$init_child" = "$services_supervisor" ]; then
				"$busybox_hack" kill "$init_child" >/dev/null 2>&1 || true
			else
				"$busybox_hack" kill -KILL "$init_child" >/dev/null 2>&1 || true
			fi
			wait "$init_child" >/dev/null 2>&1 || true
		done
	fi
	exit "$init_result"
}
trap finish_init EXIT
trap 'echo "ERROR: Initialization interrupted" >&2; exit 1' HUP INT TERM

# Initialize network
[ -n "$network_file" ] || { echo "ERROR: Missing network status path"; exit 1; }
$rm -f "$network_file" || exit 1
"$busybox_hack" sh "$sd_sbin/network.sh" &
network_pid=$!
network_wait=0
while [ ! -f "$network_file" ]; do
	if [ "$network_wait" -ge 90 ]; then
		echo "ERROR: Network initialization timed out; stopping service setup"
		$kill "$network_pid" >/dev/null 2>&1 || true
		exit 1
	fi
	$sleep 1
	network_wait=$((network_wait + 1))
done
case "$($cat "$network_file")" in
	tuya|dhcp|manual) ;;
	*) echo "ERROR: Network initialization failed; stopping service setup"; exit 1 ;;
esac

# Breakout file
breakout_file="$sys_temp/hostapd.break"

# Loop device
export loop_device="/dev/loop0"

# Device version
export device_version=`$cat $sd_etc/version.txt`

# Check, on which device we are on
export device_stock_binary_only=0
export device_has_motors=""
export device_motor_count=""
export device_article=""
export device_firmware=""
export device_bundle=""
export device_soc=""
export device_cpu=""
export device_sensor=""
export device_rtsp_available=1
export device_rtsp_main_port=554
export device_rtsp_main_path="/main_ch"
export device_rtsp_sub_port=554
export device_rtsp_sub_path="/sub_ch"
export device_rtsp_main_width=""
export device_rtsp_main_height=""
export device_rtsp_sub_width=""
export device_rtsp_sub_height=""
export device_rtsp_main_codec="H264"
export device_rtsp_sub_codec="H264"
if [ -f "$sys_usr_bin/anyka_ipc" ]; then	
	case $anyka_md5 in
        	$old_ptz_1080p_originl|$old_ptz_1080p_patched)
        		export device_var="old_ptz_1080p"
        		export device_manufacturer="LSC"
        		export device_model="Old Indoor PTZ Camera 1080p"
        		export device_deprecated=1
        		export device_has_ptz=1
        		export device_height=1080
        		export device_width=1920
        		export device_outdoor_use=0
        		export device_supported=1
        	;;
	        $indoor_ptz_1080p_originl|$indoor_ptz_1080p_patched)
        		export device_var="indoor_ptz_1080p"
        		export device_manufacturer="LSC"
        		export device_model="Indoor PTZ Camera 1080p"
        		export device_deprecated=1
        		export device_has_ptz=1
        		export device_height=1080
        		export device_width=1920
        		export device_outdoor_use=0
        		export device_supported=1
	        ;;
	        $indoor_ptz_1296p_originl|$indoor_ptz_1296p_patched)
        		export device_var="indoor_ptz_1296p"
        		export device_manufacturer="LSC"
        		export device_model="Indoor PTZ Camera 1296p"
        		export device_deprecated=0
        		export device_has_ptz=1
        		export device_height=1296
        		export device_width=2304
        		export device_outdoor_use=0
        		export device_supported=1
	        ;;
	        $outdoor_ptz_1296p_originl|$outdoor_ptz_1296p_patched)
        		export device_var="outdoor_ptz_1296p"
        		export device_manufacturer="LSC"
        		export device_model="Outdoor PTZ Camera 1296p"
        		export device_deprecated=0
        		export device_has_ptz=1
        		export device_height=1296
        		export device_width=2304
        		export device_outdoor_use=1
        		export device_supported=1
	        ;;
	        $outdoor_cam_1080p_originl|$outdoor_cam_1080p_patched)
        		export device_var="outdoor_cam_1080p"
        		export device_manufacturer="LSC"
        		export device_model="Outdoor Camera 1296p"
        		export device_deprecated=0
        		export device_has_ptz=0
        		export device_height=1296
        		export device_width=2304
        		export device_outdoor_use=1
        		export device_supported=1
	        ;;
	        $outdoor_cam_1296p_originl|$outdoor_cam_1296p_patched)
        		export device_var="outdoor_cam_1296p"
        		export device_manufacturer="LSC"
        		export device_model="Outdoor Camera 1080p"
        		export device_deprecated=1
        		export device_has_ptz=0
        		export device_height=1080
        		export device_width=1920
        		export device_outdoor_use=1
        		export device_supported=1
	        ;;
	        $ipc_xc_c323_originl)
        		export device_var="ipc_xc_c323"
        		export device_manufacturer="LSC"
        		export device_model="Indoor PTZ Camera 1080p"
        		export device_deprecated=0
        		export device_has_ptz=1
        		export device_height=1080
        		export device_width=1920
        		export device_outdoor_use=0
        		export device_supported=1
	        ;;
		$indoor_ptz_3007325_5_6_2863_125_originl)
			# This exact recovered build has a different stock runtime from older
			# 1296p cameras. Verify it before selecting its stock-only profile.
			stock_sha256=$($sha256sum "$sys_usr_bin/anyka_ipc") || {
				echo "ERROR: Cannot hash the stock 3007325.5 binary"
				exit 1
			}
			stock_sha256=$(printf '%s\n' "$stock_sha256" | $awk '{print $1}')
			if [ "$stock_sha256" != "$indoor_ptz_3007325_5_6_2863_125_sha256" ]; then
				echo "ERROR: Stock binary SHA256 does not match the 3007325.5 firmware profile"
				exit 1
			fi
			export device_var="indoor_ptz_3007325_5_6_2863_125"
			export device_manufacturer="LSC"
			export device_model="Smart PTZ Camera SI L25502"
			export device_article="3007325.5"
			export device_firmware="6.2863.125.1348"
			export device_bundle="HT_IPC286KS3_GMN_TUYA_AK3918EV330"
			export device_soc="AK3918EV330"
			export device_cpu="ARM926 (ARMv5)"
			export device_sensor="SC3332"
			export device_deprecated=0
			export device_has_motors=1
			export device_motor_count=2
			# device_has_ptz enables toolkit PTZ commands/ONVIF, not motor presence.
			# The motor CLI for this build has not been verified.
			export device_has_ptz=0
			export device_height=1296
			export device_width=2304
			export device_outdoor_use=0
			export device_supported=1
			export device_stock_binary_only=1
			export use_ipc_autopatcher=0
			export device_rtsp_available=0
			if [ "$local_rtsp_only" = "1" ]; then
				export device_rtsp_available=1
				export device_rtsp_main_port=88
				export device_rtsp_main_path="/videoMain"
				export device_rtsp_sub_port=89
				export device_rtsp_sub_path="/videoSub"
				# Mode 2 reads the active hardware configuration, not factory_cfg.ini.
				export device_rtsp_main_width=2304
				export device_rtsp_main_height=1296
				export device_rtsp_sub_width=640
				export device_rtsp_sub_height=360
				export device_rtsp_main_codec="H265"
				export device_rtsp_sub_codec="H264"
			fi
		;;
	        *)
			echo "WARNING: Unknown firmware profile; management services can still start"
			echo "No binary patch is validated for checksum $anyka_md5; factory RTSP is opt-in with local_rtsp_only=1"
        		export device_var=""
        		export device_manufacturer="Unknown"
        		export device_model="Unknown Camera"
        		export device_deprecated=0
        		export device_has_ptz=0
        		export device_height=`$cat $sys_config/_ht_hw_settings.ini 2>/dev/null | $grep "main_height =" | $awk '{print $3}' || echo 0`
        		export device_width=`$cat $sys_config/_ht_hw_settings.ini 2>/dev/null | $grep "main_width =" | $awk '{print $3}' || echo 0`
        		export device_outdoor_use=0
        		export device_supported=0
	        ;;
	esac
else
	echo "Missing $sys_usr_bin/anyka_ipc"
	exit 1
fi

# Older profiles used this flag for both motor presence and toolkit control.
[ -n "$device_has_motors" ] || export device_has_motors="$device_has_ptz"

echo "Device hostname is: $system_hostname"
echo "Device MAC is: $device_mac"
echo "Device UID: $device_uid"
echo "Device manufacturer: $device_manufacturer"
echo "Device model: $device_model"
echo "Device is deprecated: $device_deprecated"
echo "Device has motor hardware: $device_has_motors"
[ -z "$device_motor_count" ] || echo "Device motor count: $device_motor_count"
echo "Toolkit PTZ control available: $device_has_ptz"
[ -z "$device_article" ] || echo "Device article: $device_article"
[ -z "$device_firmware" ] || echo "Stock firmware build: $device_firmware"
echo "Device resolution height: $device_height px"
echo "Device resolution width: $device_width px"
echo "Device can be used outdoor: $device_outdoor_use"
echo "Device profile recognized: $device_supported (does not imply an available binary patch)"
echo "Anyka IPC Checksum: $anyka_md5"

# Compare function
compare() {
	src="$1"
	dst="$2"
	
	[ "$dst" = "" ] && return 1
	
	echo -n "Comparing $src and $dst..."
	src_csum=`$md5sum "$src" | $grep "$src" | $awk '{print \$1}'`
	dst_csum=`$md5sum "$dst" | $grep "$dst" | $awk '{print \$1}'`
	
	if [ "$src_csum" = "$dst_csum" ]; then
		echo "identical"
		return 0
	fi

	echo "mismatch, update needed"
	return 1
}

# Create paths on sd, if not exist
echo "Creating directory structure"
for i in $sd_etc $sd_bin $sd_lib $sd_sbin $sd_backup $sd_www $sd_log $sd_patch $sd_overlay $sd_mnt $sd_crontabs; do
	$mkdir -p $i >/dev/null 2>&1 && echo " - $i"
done

# Create enabled files on tmp
echo "Creating enabled files"
for i in $file_ftp_enabled $file_http_enabled $file_telnet_enabled $file_cron_enabled $file_onvif_enabled $file_mqtt_enabled; do
	touch $i > /dev/null 2>&1
done

# Swap configuration (disabled, because kernel does not support it, yet)
swap_file="$sd_overlay/swap.fil"
swap_space="64"

# Create swap file, if requested
if [ -n "$swap_space" -a "$swap_space" -gt 0 -a -n "$swap_file" ]; then
	if [ ! -f "$swap_file" ]; then
		echo "Generating $swap_space MB swap file in $swap_file"
		$dd if=/dev/zero of=$swap_file bs=1M count=$swap_space
		$mkswap $swap_file
	fi
	
	echo "Activating $swap_space MB swap file $swap_file"
	$swapon $swap_file
fi

# The stock 3007325.5 application resolves both commands through PATH. Its only
# installed aliases are in /sbin, which the overlay will cover below.
configure_overlay_network_tools()
{
	local network_tool
	if [ "$anyka_md5" = "7c2a124cdd607ebef63fb66d063b6a87" ]; then
		for network_tool in ifconfig udhcpc; do
			$ln -sf "$sd_mnt/real/bin/busybox" "$sd_mnt/override/sbin/$network_tool" || {
				echo "ERROR: Cannot preserve stock network tool $network_tool" >&2
				return 1
			}
		done
	else
		$rm -f "$sd_mnt/override/sbin/ifconfig"
		$rm -f "$sd_mnt/override/sbin/udhcpc"
	fi
	return 0
}

overlay_dirs="bin sbin lib lib/modules usr/bin usr/sbin usr/share usr/lib usr/local usr/modules"

# Create overlay filesystem
if [ ! -f "$sd_overlay/fs.img" ]; then
	$touch $setup_lock_file
	echo "Creating overlay filesystem"
	loop_device="/dev/loop$($losetup -a | $wc -l)"
	$dd if=/dev/zero of=$sd_overlay/fs.img bs=1k count=32768 && \
	$losetup $loop_device $sd_overlay/fs.img && \
	$mkfs_vfat $loop_device && \
	$mount $loop_device $sd_mnt || exit 1
	echo -n "Setting up overlay filesystem..."
	$mkdir -p $sd_mnt/override/bin
	$mkdir -p $sd_mnt/override/sbin
	for i in $overlay_dirs; do
		$mkdir -p $sd_mnt/real/$i
		$mkdir -p $sd_mnt/$i
	done
	echo "done"
else
	echo -n "Mounting overlay filesystem..."
	loop_device="/dev/loop$($losetup -a | $wc -l)"
	$losetup $loop_device $sd_overlay/fs.img && \
	$mount $loop_device $sd_mnt && \
	echo "done" || exit 1
fi

# Prepare overlay filesystem
if [ -f "$sd_overlay/fs.img" ]; then
	echo -n "Preparing overlay filesystem..."
	$mkdir -p $sd_mnt/override/bin
	$mkdir -p $sd_mnt/override/sbin
	$mount -t tmpfs -o size=1K tmpfs $sd_mnt/override/bin
	$mount -t tmpfs -o size=1K tmpfs $sd_mnt/override/sbin
	for i in $overlay_dirs; do
		$mkdir -p $sd_mnt/real/$i
		$mkdir -p $sd_mnt/override/$i
		$mkdir -p $sd_mnt/$i
		$mount -t tmpfs -o size=2K tmpfs $sd_mnt/$i
		$find /$i -maxdepth 1 -type f -exec $cp {} $sd_mnt/real/$i \;
		if [ "$i" != "bin" -a "$i" != "sbin" -a "$i" != "usr/bin" -a "$i" != "usr/sbin" ]; then
			$find /$i -maxdepth 1 -type l -exec $ln -sf $sd_mnt/{} $sd_mnt/real/$i \;
		fi
		$find $sd_mnt/real/$i -maxdepth 1 -type f -exec $ln -sf {} $sd_mnt/$i \;
	done
	for i in `$sd_mnt/real/bin/busybox --install 2>&1 | $cut -d : -f2 | $sed -e 's/\/usr//g'`; do 
		$ln -sf $sd_mnt/real/bin/busybox $sd_mnt/$i 
		$ln -sf $sd_mnt/real/bin/busybox $sd_mnt/override/$i 
	done
	for i in `$busybox --install 2>&1 | $cut -d : -f2`; do 
		$ln -sf $busybox $sd_mnt/$i 
		$ln -sf $busybox $sd_mnt/override/$i 
	done
	$find $sys_bin -maxdepth 1 -type l -exec $ln -sf $sd_mnt/real/bin/busybox $sd_mnt/.{} \;
	$find $sys_sbin -maxdepth 1 -type l -exec $ln -sf $sd_mnt/real/bin/busybox $sd_mnt/.{} \;
	$find $sys_bin -maxdepth 1 -type l -exec $ln -sf $sd_mnt/real/bin/busybox $sd_mnt/override{} \;
	$find $sys_sbin -maxdepth 1 -type l -exec $ln -sf $sd_mnt/real/bin/busybox $sd_mnt/override{} \;
	$find $sd_bin -maxdepth 1 -type f -exec $ln -sf {} $sd_mnt/bin \;
	$find $sd_sbin -maxdepth 1 -type f -not -name "*.sh" -exec $ln -sf {} $sd_mnt/sbin \;
	$find $sd_lib -maxdepth 1 -type f -exec $ln -sf {} $sd_mnt/lib \;
	$find $sd_lib -maxdepth 1 -type l -exec $ln -sf {} $sd_mnt/lib \;
	$find $sd_lib/pkgconfig -maxdepth 1 -type f -exec $ln -sf {} $sd_mnt/lib/pkgconfig \;
 	$ln -sf $sd_mnt/real/bin/busybox $sd_mnt/override/bin/busybox
 	$ln -sf $sd_mnt/real/bin/busybox $sd_mnt/override/sbin/busybox
 	$ln -sf $sd_mnt/real/bin/mtd_debug $sd_mnt/override/bin/mtd_debug
 	$ln -sf $sd_mnt/real/bin/mtd_debug $sd_mnt/bin/mtd_debug
	configure_overlay_network_tools || exit 1
 	for i in jmacs jpico jstar rjoe; do
		$ln -sf $sd_bin/joe $sd_mnt/bin/$i
	done
	$ln -sf $sd_share/joe $sd_mnt/usr/share
	$ln -sf $sd_share/aclocal $sd_mnt/usr/share
	echo "done"
	echo -n "Mounting overlay over /bin..."
	$mount --bind $sd_mnt/override/bin /bin >/dev/null 2>&1 && echo "done" || echo "failed"
	echo -n "Mounting overlay over /sbin..."
	$mount --bind $sd_mnt/override/sbin /sbin >/dev/null 2>&1 && echo "done" || echo "failed"
fi

# Copy shadow and passwd files and clean them in case they were edited in windows
echo "Copying and linking shadow and passwd files to operating system"
for i in shadow passwd; do
	$cp $sd_config/$i $sys_config/$i
done

# Create certificates, if not exists
if [ ! -e $sd_etc/mosquitto/certs/ca.crt ]; then
	echo "Generating mosquitto ca and certificate"
	mkdir -p $sd_etc/mosquitto/certs
	TARGET="$sd_etc/mosquitto/certs" \
	HOSTLIST="m2.tuyaeu.com mq.gw.tuyaeu.com m2-weaz.tuyaeu.com m2.tuyacn.com mq.gw.tuyacn.com m2-ceaz.tuyacn.com m2.tuyaus.com mq.gw.tuyaus.com m2-ueaz.tuyaus.com" \
	$sd_sbin/generate-ca.sh
fi

# Copy crontabs
echo -n "Copying crontabs from $sd_crontabs to $sys_crontabs..."
$mkdir -p $sys_crontabs >/dev/null 2>&1
$cp $sd_crontabs/* $sys_crontabs && echo "done" || echo "failed"

# Issue #2 mitigation: Clean logseq* and log_seq_stat files before backup
# These files can cause flash exhaustion and should never be backed up
echo -n "Cleaning up problematic flash files from /etc/config..."
$rm -f /etc/config/logseq* /etc/config/log_seq_stat >/dev/null 2>&1 || true
echo "done"

# Make a backup of the origin firmware files
if [ ! -e $sd_backup/root.tar ]; then
	echo "Creating backup of root-fs"
	$tar -cvpf $sd_backup/root.tar /bin /data /lib /sbin
fi
for i in etc usr var; do
	if [ ! -e $sd_backup/$i.tar ]; then
		echo "Creating backup of $i"
		$tar -cvpf $sd_backup/$i.tar /$i
	fi
done

# Issue #2 mitigation: Create dedicated backup for critical /etc/config
echo -n "Creating backup of /etc/config (mtdblock6)..."
if [ ! -e $sd_backup/config.tar ]; then
	$tar -cpf $sd_backup/config.tar /etc/config >/dev/null 2>&1 && echo "done" || echo "failed"
else
	echo "already exists"
fi

# Issue #2 mitigation: Copy /etc/config files to backup directory
echo -n "Copying /etc/config files to backup directory..."
$mkdir -p $sd_backup/config >/dev/null 2>&1
$cp /etc/config/* $sd_backup/config/ 2>/dev/null || true
echo "done"

# Issue #2 mitigation: Create checksums of all /etc/config files
echo -n "Creating MD5 checksums of /etc/config files..."
cd /etc/config && $find . -type f -not -name "logseq*" -not -name "log_seq_stat" -exec $md5sum {} \; > $sd_backup/config.md5 2>/dev/null
cd - >/dev/null 2>&1
echo "done"

if [ ! -e $sd_backup/filesystem.lst ]; then
	echo -n "Inventory of files, links and sockets..."
	$find / -type f -or -type l -or -type s > $sd_backup/filesystem.lst && echo "done" || echo "failed"
fi
for i in 1 2 3 4 5 6 7; do
	if [ ! -e $sd_backup/mtdblock$i.img ]; then
		echo -n "Creating backup image of mtdblock$i..."
		$dd if=/dev/mtdblock$i of=$sd_backup/mtdblock$i.img bs=1 >/dev/null 2>&1 && echo "done" || echo "failed"
	fi
done

# Check, whether anyka_ipc exists
# A previously generated binary is not valid for a stock-only firmware profile.
if [ "${device_stock_binary_only:-0}" = "1" ]; then
	$rm -f "$sd_bin/anyka_ipc_patched"
fi
if [ ! -e "$sd_bin/anyka_ipc" ]; then
	echo -n "Creating copy of firmwares anyka_ipc..." 
	$rm -f "$sd_bin/anyka_ipc_patched"
	$cp "$sys_usr_bin/anyka_ipc" "$sd_bin/anyka_ipc" && echo "done" || exit 1
fi
if [ -e "$sd_bin/anyka_ipc" ]; then
	if ! compare "$sys_usr_bin/anyka_ipc" "$sd_bin/anyka_ipc"; then
		# A generated patch belongs to the old firmware, not the new stock copy.
		$rm -f "$sd_bin/anyka_ipc_patched"
		$cp "$sys_usr_bin/anyka_ipc" "$sd_bin/anyka_ipc" || exit 1
	fi
fi

# Check, whether anyka_ipc_patched exists and if there are patches
if [ ! -e "$sd_bin/anyka_ipc_patched" -a -e "$sd_bin/anyka_ipc" -a "$use_ipc_autopatcher" = "1" -a "$local_rtsp_only" != "1" -a "${device_stock_binary_only:-0}" != "1" ]; then
	anyka_checksum=`$md5sum -b "$sd_bin/anyka_ipc" | $awk '{print $1}'`
	patch_file=`$find "$sd_patch" -type f -name "$anyka_checksum.ips.gz" | $head -n 1`
	
	if [ -n "$patch_file" -a -f "$patch_file" ]; then
		if "$busybox_hack" sh "$sd_sbin/apply_ips_patch.sh" "$patch_file" "$sd_bin/anyka_ipc" "$sd_bin/anyka_ipc_patched"; then
			$touch "$setup_lock_file"
			anyka_ipc_patched_checksum=`$md5sum "$sd_bin/anyka_ipc_patched" | $awk '{print $1}'`
			patched_var="${device_var}_patched"
			if [ -n "$device_var" -a -f "$sd_etc/anyka_checksums.conf" ]; then
				$sed -i -e "s/^$patched_var=.*/$patched_var=$anyka_ipc_patched_checksum/g" "$sd_etc/anyka_checksums.conf"
				. "$sd_etc/anyka_checksums.conf"
			fi
		else
			echo "WARNING: Binary patch failed; keeping the stock anyka_ipc"
			$rm -f "$sd_bin/anyka_ipc_patched"
		fi
	fi
fi

# Check, whether ssl exists
[ ! -d $sys_config/ssl ] && $mkdir -p $sys_config/ssl >/dev/null 2>&1
[ ! -f $sys_config/ssl/ca-bundle ] && $touch $sys_config/ssl/ca-bundle
echo -n "Linking ssl ca-bundle..."
$mount --bind $sd_config/ssl/ca-bundle $sys_config/ssl/ca-bundle && echo "done" || echo "failed"

# Check, whether joe exists
if [ ! -d $sys_config/joe ]; then
	echo -n "Creating and linking joe..."
	$mkdir -p $sys_config/joe >/dev/null 2>&1 && \
	$mount --bind $sd_config/joe $sys_config/joe && echo "done" || echo "failed"
fi

# Check, whether anyka_cfg.ini exists
if [ ! -e $sd_config/anyka_cfg.ini ]; then
	echo -n "Creating anyka_cfg.ini from factory_cfg.ini file..."
	$cp $sys_usr_local/factory_cfg.ini $sd_config/anyka_cfg.ini && echo "done" || echo "failed"
fi
if [ -e "$sd_config/anyka_cfg.ini" ]; then
	compare $sys_usr_local/factory_cfg.ini $sd_config/anyka_cfg.ini || $cp $sys_usr_local/factory_cfg.ini $sd_config/anyka_cfg.ini 
fi

# Check, whether _ht_hw_settings.ini exists
if [ ! -e $sd_config/_ht_hw_settings.ini ]; then
	echo -n "Creating _ht_hw_settings.ini file..."
	$cp $sys_config/_ht_hw_settings.ini $sd_config && echo "done" || echo "failed" 
fi
if [ -e $sd_config/_ht_hw_settings.ini ]; then
	compare $sys_config/_ht_hw_settings.ini $sd_config/_ht_hw_settings.ini || $cp $sys_config/_ht_hw_settings.ini $sd_config 
fi

# Check, whether _ht_sw_settings.ini exists and add missing template data if required
if [ "${device_stock_binary_only:-0}" = "1" ]; then
	# The exact recovered build owns this schema. Keep its persistent file and
	# values intact; a generic template can change firmware network state.
	echo "Preserving stock software settings for this firmware profile"
	[ -f "$sys_config/_ht_sw_settings.ini" ] && \
		$cp "$sys_config/_ht_sw_settings.ini" "$sd_config/_ht_sw_settings.ini" || exit 1
else
if [ ! -e $sd_config/_ht_sw_settings.ini ]; then
	echo -n "Creating _ht_sw_settings.ini file..."
	$cp $sys_config/_ht_sw_settings.ini $sd_config && echo "done" || echo "failed" 
	# Sanitize any malformed lines (remove leading ':' characters and optional "config:" prefix)
	if [ -f "$sd_config/_ht_sw_settings.ini" ]; then
		$sed -i -e 's/^:*config://' -e 's/^:*//' "$sd_config/_ht_sw_settings.ini" >/dev/null 2>&1 || true
	fi
	if [ -f "$sd_config/_ht_sw_config.tmpl" ]; then
  	  while IFS= read -r line; do
            case "$line" in
              int*|bool*|enum*|str*)
                key=$(echo "$line" | $awk '{print $1}')
                if ! $grep -q "^$key" "$sys_config/_ht_sw_settings.ini"; then
                    echo "$line" >> "$sd_config/_ht_sw_settings.ini"
                fi
                ;;
            esac
	  done < "$sd_config/_ht_sw_config.tmpl"
	  $sed -i '/^$/d' "$sd_config/_ht_sw_settings.ini"
  	  compare $sd_config/_ht_sw_settings.ini $sys_config/_ht_sw_settings.ini || $cp $sd_config/_ht_sw_settings.ini $sys_config 
	fi
fi
if [ -e $sd_config/_ht_sw_settings.ini ]; then
	# Sanitize persisted settings file in SD overlay as well
	if [ -f "$sd_config/_ht_sw_settings.ini" ]; then
		$sed -i -e 's/^:*config://' -e 's/^:*//' "$sd_config/_ht_sw_settings.ini" >/dev/null 2>&1 || true
	fi
	# Also sanitize and deduplicate the system config to avoid duplicated options
	if [ -f "$sys_config/_ht_sw_settings.ini" ]; then
		# remove leading ':' characters and optional 'config:' prefix
		$sed -e 's/^:*config://' -e 's/^:*//' "$sys_config/_ht_sw_settings.ini" > "$sys_temp/_ht_sw_settings.ini.sanitize" 2>/dev/null || true
		# ensure a [config] header exists
		$grep -q '^\[config\]' "$sys_temp/_ht_sw_settings.ini.sanitize" || (echo '[config]' | cat - "$sys_temp/_ht_sw_settings.ini.sanitize" > "$sys_temp/_ht_sw_settings.ini.sanitize.1" && $mv "$sys_temp/_ht_sw_settings.ini.sanitize.1" "$sys_temp/_ht_sw_settings.ini.sanitize")
		# deduplicate keys, keep the last occurrence of each key
		$awk 'FNR==NR{ if($0 ~ /=/){ split($0,a,"="); k=a[1]; gsub(/^[ \t]+|[ \t]+$/,"",k); cnt[k]++ } next }{ if($0 ~ /=/){ split($0,a,"="); k=a[1]; gsub(/^[ \t]+|[ \t]+$/,"",k); cnt[k]--; if(cnt[k]==0) print $0 } else print $0 }' "$sys_temp/_ht_sw_settings.ini.sanitize" "$sys_temp/_ht_sw_settings.ini.sanitize" > "$sys_temp/_ht_sw_settings.ini.clean" && $mv "$sys_temp/_ht_sw_settings.ini.clean" "$sys_config/_ht_sw_settings.ini"
	fi
	compare $sys_config/_ht_sw_settings.ini $sd_config/_ht_sw_settings.ini || $cp $sys_config/_ht_sw_settings.ini $sd_config 
fi
fi

# Check, whether libavssdkbeta.so exists
if [ -f "$sys_usr_lib/libavssdkbeta.so" ]; then
	if [ ! -e "$sd_lib/libavssdkbeta.so" ]; then
		echo -n "Creating copy of libavssdkbeta.so file..."
		$cp "$sys_usr_lib/libavssdkbeta.so" "$sd_lib" && echo "done" || echo "failed"
	else
		compare "$sys_usr_lib/libavssdkbeta.so" "$sd_lib/libavssdkbeta.so" || \
			$cp "$sys_usr_lib/libavssdkbeta.so" "$sd_lib"
	fi
fi

# Prepare and mount factory_cfg.ini
if [ -e "$sd_config/anyka_cfg.ini" ]; then
	echo -n "Updating anyka_cfg.ini file..."
	$sed -i -e 's/^[[:space:]]*rtsp[[:space:]]*=[[:space:]]*0\([[:space:]]*\([#;].*\)\{0,1\}\)$/rtsp = 1\1/' \
		-e 's/^[[:space:]]*onvif[[:space:]]*=[[:space:]]*0\([[:space:]]*\([#;].*\)\{0,1\}\)$/onvif = 1\1/' \
		"$sd_config/anyka_cfg.ini" && \
	echo "done" || echo "failed"
	echo -n "Binding anyka_cfg.ini from sd card to $sys_usr_local/factory_cfg.ini file..."
	$mount --bind "$sd_config/anyka_cfg.ini" "$sys_usr_local/factory_cfg.ini" && echo "done" || echo "failed"
	echo -n "Copying anyka_cfg.ini from sd card to $sys_config..."
	$cp "$sd_config/anyka_cfg.ini" "$sys_config/anyka_cfg.ini" && echo "done" || echo "failed"
fi

# Check, whether a backup of tuya dbs exists
for i in $sys_config/tuya_enckey.db $sys_config/tuya_user.db $sys_config/tuya_user.db_bak; do
	if [ -e $i ]; then
		echo -n "Backing up $i file..."
		$cp $i $sd_config && echo "done" || echo "failed"
	fi
	if [ -e $i ]; then
		filename=`$basename $i`
		compare $i $sd_config/$filename || $cp $i $sd_config 
	fi
done

# Kill running telnetd and tcpsvd, if any
for i in telnetd tcpsvd; do
	proc=$($pgrep -f "$i" || true)
	if [ "$proc" != "" ]; then 
		echo -n "Killing $i with PID $proc..." 
		$kill -KILL $proc && echo "done" || echo "failed"
	fi
done

# Disable any kind of firmware update
for i in update_tmp.sh update_tmp_bak.sh update_tmp_ota.sh tf_update.sh; do
	echo -n "Disabling script $sys_usr_sbin/$i..."
	$mount --bind $sd_sbin/exit.sh $sys_usr_sbin/$i && echo "done" || echo "failed"
done

# Block Tuya Servers in case of offline mode
if [ "$use_offline_mode" != "" ]; then
	echo "OFFLINE MODE ENABLED"
	$mount --bind $sd_etc/hosts.offline /etc/hosts
fi

# Create onvif.token file, if not exists
[ -f "$sd_etc/onvif.token" ] || $dd if=/dev/urandom bs=1 count=32 2>/dev/null | $sha256sum | $awk '{print $1}' > $sd_etc/onvif.token

# Construct a small bootstrap; the runtime wrapper reloads configuration on each
# firmware watchdog restart, including the optional custom configuration file.
echo -n "Creating anyka_ipc_wrapper..."
{
	echo '#!/bin/sh'
	echo "export hack=\"$sd_path/HACK\""
	echo "exec \"$busybox_hack\" sh \"$sd_sbin/anyka_ipc_wrapper.sh\" \"$anyka_md5\""
} > "$sys_temp/anyka_ipc_wrapper.sh" && echo "done" || exit 1

# Prepare anyka ipc wrapper and configuration
echo -n "Enabling _ht_hw_settings.ini file..."
hardware_settings_source="$sys_config/_ht_hw_settings.ini"
[ -f "$hardware_settings_source" ] || hardware_settings_source="$sys_usr_local/_ht_hw_settings.ini"
$cp "$hardware_settings_source" "$sys_temp/_ht_hw_settings.ini.new" && \
$mv "$sys_temp/_ht_hw_settings.ini.new" "$sys_temp/_ht_hw_settings.ini" && \
$mount --bind "$sys_temp/_ht_hw_settings.ini" "$sys_config/_ht_hw_settings.ini" && \
echo "done" || echo "failed"
echo -n "Enabling anyka_ipc_wrapper..."
$chmod +x $sys_temp/anyka_ipc_wrapper.sh && \
$mount --bind $sys_temp/anyka_ipc_wrapper.sh $sys_usr_bin/anyka_ipc && \
echo "done" || echo "failed"

# Making the device silent, by disabling some disturbing sound files
touch $sys_temp/empty.mp3
$find $sys_usr_share -type f -name "8k16_*.mp3" -and -not -name "8k16_siren.mp3" -exec $mount --bind $sys_temp/empty.mp3 {} \;

# Binding sound files from SD
for a in `$find $sd_sound -type f -name "*.mp3" -not -name "8k16*"`; do
	i=`$basename $a`	
	echo -n "Binding soundfile $i..."
	[ -f "$sd_sound/$i" -a -f "$sys_usr_share/$i" ] && $mount --bind $sd_sound/$i $sys_usr_share/$i && echo "done" || echo "skipped"
done

# Binding profile
if [ -f "$sd_etc/profile" ]; then
	echo -n "Binding profile..."
	$mount --bind $sd_etc/profile $sys_etc/profile && echo "done" || echo "failed"
fi

# Custom scripts run after init
[ -n "$custom_pre_init_async" -a -x "$custom_pre_init_async" ] && $custom_pre_init_async &
[ -n "$custom_pre_init" -a -x "$custom_pre_init" ] && $custom_pre_init

# Sync anything
$sync

# Start and supervise services without blocking the stock startup indefinitely.
start_service_supervisor()
{
	local services_pipe="$sys_temp/services-startup.pipe.$$" services_child="" services_logger="" services_result
	drain_service_log()
	{
		local services_reader=""
		# Async commands can have fd 0 replaced with /dev/null before <&0 is
		# applied. Retain the FIFO on a separate descriptor for both readers.
		exec 3<&0
		stop_service_log_reader()
		{
			if [ -n "$services_reader" ]; then
				"$busybox_hack" kill -KILL "$services_reader" >/dev/null 2>&1 || true
				wait "$services_reader" >/dev/null 2>&1 || true
			fi
		}
		trap 'stop_service_log_reader; exec 3<&-; exit 0' HUP INT TERM
		# dd writes each short read immediately. head buffers short diagnostics
		# until EOF, which daemons retaining the FIFO writer may never provide.
		"$busybox_hack" dd bs=4096 count=65536 iflag=count_bytes status=none <&3 &
		services_reader=$!
		wait "$services_reader"
		services_reader=""
		"$busybox_hack" cat <&3 > /dev/null &
		services_reader=$!
		wait "$services_reader"
		services_reader=""
		exec 3<&-
		trap - HUP INT TERM
	}
	cleanup_service_startup()
	{
		if [ -n "$services_child" ]; then
			"$busybox_hack" kill -KILL "$services_child" >/dev/null 2>&1 || true
			wait "$services_child" >/dev/null 2>&1 || true
		fi
		if [ -n "$services_logger" ]; then
			"$busybox_hack" kill "$services_logger" >/dev/null 2>&1 || true
			wait "$services_logger" >/dev/null 2>&1 || true
		fi
		"$busybox_hack" rm -f "$services_pipe"
	}
	trap 'cleanup_service_startup; exit 1' HUP INT TERM
	"$busybox_hack" mkfifo "$services_pipe" || exit 1
	# Drain all output while retaining at most 64 KiB. Keep the logger separate
	# from the service process so its output limit does not kill a service.
	drain_service_log < "$services_pipe" > "$sd_log/services-startup.log" &
	services_logger=$!
	"$busybox_hack" timeout -k 5 60 "$busybox_hack" ash "$sd_sbin/services.sh" > "$services_pipe" 2>&1 &
	services_child=$!
	wait "$services_child"
	services_result=$?
	services_child=""
	# Allow the reader to consume the final pipe buffer. Background service
	# daemons may retain a writer FD, so never require EOF to continue startup.
	"$busybox_hack" sleep 1
	cleanup_service_startup
	services_logger=""
	if [ ! -f "$sys_temp/services.run" ]; then
		echo "ERROR: First services process exited before readiness (status $services_result)"
		exit 1
	fi
	while [ ! -f "$breakout_file" ]; do
		"$busybox_hack" sleep 30
		[ ! -f "$breakout_file" ] || break
		"$busybox_hack" timeout -k 5 60 "$busybox_hack" ash "$sd_sbin/services.sh" >/dev/null 2>&1 &
		services_child=$!
		wait "$services_child"
		services_child=""
	done
	trap - HUP INT TERM
}

# Run services.sh on SD card every 30 seconds
if [ -x "$sd_sbin/services.sh" ]; then
	# Custom scripts run once before services
	[ -n "$custom_pre_services_once_async" -a -x "$custom_pre_services_once_async" ] && $custom_pre_services_once_async &
	[ -n "$custom_pre_services_once" -a -x "$custom_pre_services_once" ] && $custom_pre_services_once
	if [ -f "$setup_lock_file" ]; then
		echo "Waiting 60 seconds to initiate reboot"
		$rm -f $setup_lock_file >/dev/null 2>&1
		$sleep 60
		$reboot
	else
		echo "Running services.sh"
		"$busybox_hack" rm -f "$sys_temp/services.run" || exit 1
		if [ -f "$sd_log/services-startup.log" ]; then
			"$busybox_hack" mv -f "$sd_log/services-startup.log" "$sd_log/services-startup.previous.log" || exit 1
		fi
		start_service_supervisor < /dev/null &
		services_supervisor=$!
		services_wait=0
		while [ ! -f "$sys_temp/services.run" ]; do
			if ! "$busybox_hack" kill -0 "$services_supervisor" 2>/dev/null; then
				wait "$services_supervisor" >/dev/null 2>&1 || true
				echo "ERROR: Services stopped before readiness; releasing stock startup"
				exit 1
			fi
			if [ "$services_wait" -ge 45 ]; then
				echo "ERROR: Services readiness timed out; releasing stock startup"
				"$busybox_hack" kill "$services_supervisor" >/dev/null 2>&1 || true
				wait "$services_supervisor" >/dev/null 2>&1 || true
				exit 1
			fi
			"$busybox_hack" sleep 1
			services_wait=$((services_wait + 1))
		done
       	fi
	# Custom scripts run once after services
	if [ -n "$custom_post_services_once_async" ] && [ -x "$custom_post_services_once_async" ]; then
		"$custom_post_services_once_async" &
	fi
	if [ -n "$custom_post_services_once" ] && [ -x "$custom_post_services_once" ]; then
		"$custom_post_services_once" || exit 1
	fi
else
	echo "No services.sh file. Exitting."
	exit 1
fi

# Initialization completed; optional absent hooks are not a startup failure.
services_supervisor=""
network_pid=""
exit 0
