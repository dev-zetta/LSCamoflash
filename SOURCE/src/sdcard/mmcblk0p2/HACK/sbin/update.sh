#!/bin/sh

[ -n "$hack" -a -n "$device_uid" ] || exit 1

# Version parsing is shared by installed and remotely supplied versions.
update_version_valid()
{
	local version_major=${1%%.*} version_rest=${1#*.} version_minor version_revision
	version_minor=${version_rest%%.*}
	version_revision=${version_rest#*.}
	case "$version_major" in ''|0*|*[!0-9]*) return 1 ;; esac
	case "$version_minor" in [0-9][0-9]) ;; *) return 1 ;; esac
	case "$version_revision" in [0-9][0-9][0-9][0-9]) ;; *) return 1 ;; esac
	[ "$1" = "$version_major.$version_minor.$version_revision" ]
}

update_version_newer()
{
	update_version_valid "$1" && update_version_valid "$2" || return 2
	local new_major=${1%%.*} old_major=${2%%.*} new_rest=${1#*.} old_rest=${2#*.}
	local new_minor=${new_rest%%.*} old_minor=${old_rest%%.*}
	local new_revision=${new_rest#*.} old_revision=${old_rest#*.}
	# Compare decimal text so larger majors never overflow shell integers.
	if [ "${#new_major}" -ne "${#old_major}" ]; then
		[ "${#new_major}" -gt "${#old_major}" ]; return
	fi
	if [ "$new_major" != "$old_major" ]; then
		[ "$new_major" \> "$old_major" ]; return
	fi
	if [ "$new_minor" != "$old_minor" ]; then
		[ "$new_minor" \> "$old_minor" ]; return
	fi
	[ "$new_revision" \> "$old_revision" ]
}

VERSION=$(cat "$hack/etc/version.txt") || exit 1
update_version_valid "$VERSION" || {
	echo "Error: Invalid installed version; expected M.xx.xxxx with a positive major."
	exit 1
}

echo -n "Updater is starting up at " && date

updatetgz="$sd_update/update.tgz"

# Copy update files through same-directory temporaries, then rename them.
# In particular, BusyBox may still be executing from either card partition.
# Truncating that inode fails with ETXTBSY; unlink-before-copy risks losing it.
update_copy_tree()
{
	local update_source="$1" update_target="$2" update_entry update_name update_temp
	[ ! -L "$update_target" ] || return 1
	$mkdir -p "$update_target" || return 1
	for update_entry in "$update_source"/* "$update_source"/.[!.]* "$update_source"/..?*; do
		[ -e "$update_entry" ] || [ -L "$update_entry" ] || continue
		update_name=${update_entry##*/}
		if [ -d "$update_entry" ] && [ ! -L "$update_entry" ]; then
			update_copy_tree "$update_entry" "$update_target/$update_name" || return 1
		elif [ -f "$update_entry" ]; then
			[ ! -d "$update_target/$update_name" ] || return 1
			update_temp="$update_target/.$update_name.update-$$"
			[ ! -e "$update_temp" ] && [ ! -L "$update_temp" ] || return 1
			if ! $cp -aL "$update_entry" "$update_temp"; then
				$rm -f "$update_temp"
				return 1
			fi
			if ! $mv -f "$update_temp" "$update_target/$update_name"; then
				$rm -f "$update_temp"
				return 1
			fi
		else
			return 1
		fi
	done
}

if [ -d "$sd_update" ]; then
	echo "Installing update: $VERSION" >> $sd_log/update.log
	# The hook supports a FAT first partition or a whole-device FAT card.
	# Never copy boot files to the covered tmpfs after a failed mount.
	update_boot_path="$sys_mnt"
	update_mounted=0
	update_mount_row=$(awk -v path="$sys_mnt" '$2 == path { row=$0 } END { print row }' /proc/mounts)
	if ! printf '%s\n' "$update_mount_row" | awk '
		$1 ~ /^\/dev\/mmcblk0(p1)?$/ &&
		($3 == "vfat" || $3 == "fat" || $3 == "msdos") &&
		$4 ~ /(^|,)rw(,|$)/ { valid=1 } END { exit !valid }'; then
		# On a single FAT card, /tmp/sd is the retained bind of the boot root.
		update_sd_row=$(awk -v path="$sd_path" '$2 == path { row=$0 } END { print row }' /proc/mounts)
		if printf '%s\n' "$update_sd_row" | awk '
			$1 ~ /^\/dev\/mmcblk0(p1)?$/ &&
			($3 == "vfat" || $3 == "fat" || $3 == "msdos") &&
			$4 ~ /(^|,)rw(,|$)/ { valid=1 } END { exit !valid }'; then
			update_boot_path="$sd_path"
		else
			update_boot_device=/dev/mmcblk0p1
			[ -b "$update_boot_device" ] || update_boot_device=/dev/mmcblk0
			[ -b "$update_boot_device" ] && mount -t vfat -o rw "$update_boot_device" "$sys_mnt" || {
				echo "ERROR: Boot card mount failed; update retained" >> "$sd_log/update.log"
				exit 1
			}
			update_mounted=1
		fi
	fi
	update_copy_status=0
	[ ! -x "$sd_update/update-pre.sh" ] || "$sd_update/update-pre.sh" "$VERSION" >> "$sd_log/update.log" 2>&1 || update_copy_status=1
	if [ "$update_copy_status" = 0 ] && [ -d "$sd_update/mmcblk0p1" ]; then
		update_copy_tree "$sd_update/mmcblk0p1" "$update_boot_path" >> "$sd_log/update.log" 2>&1 || update_copy_status=1
	fi
	if [ "$update_copy_status" = 0 ] && [ -d "$sd_update/mmcblk0p2" ]; then
		update_copy_tree "$sd_update/mmcblk0p2" "$sd_path" >> "$sd_log/update.log" 2>&1 || update_copy_status=1
	fi
	if [ "$update_copy_status" = 0 ] && [ -x "$sd_update/update-post.sh" ]; then
		"$sd_update/update-post.sh" "$VERSION" >> "$sd_log/update.log" 2>&1 || update_copy_status=1
	fi
	$sync || update_copy_status=1
	if [ "$update_mounted" = 1 ]; then
		umount "$sys_mnt" >> "$sd_log/update.log" 2>&1 || update_copy_status=1
	fi
	if [ "$update_copy_status" != 0 ]; then
		echo "ERROR: Update failed; staged files retained for diagnosis" >> "$sd_log/update.log"
		exit 1
	fi
 
        $rm -rf $sd_update
        $rm -rf $sd_overlay
	echo -n "Update installed: " >> $sd_log/update.log
	date >> $sd_log/update.log
        $mv $sd_log/update.log $sd_log/update-last.log
        exit
fi

[ -n "$update_url" ] || exit 1
UPDATE_URL=$(echo "$update_url" | sed -e "s/%device_uid%/$device_uid/g")
agent="LSCamoflash/$VERSION;uid=$device_uid"
curl_cmd="$curl -A $agent"

[ "$update_ssl_ignore" = "1" ] && curl_cmd="$curl_cmd --insecure"

# Fetch latest version
UPDATE=$($curl_cmd "$UPDATE_URL/version.txt" 2>/dev/null)
if [ -z "$UPDATE" ]; then
    echo "Error: Unable to fetch update version."
    exit 1
fi

update_version_valid "$UPDATE" || {
    echo "Error: Invalid update version; expected M.xx.xxxx with a positive major."
    exit 1
}

echo -n "Date: " > $sd_log/update.log
date >> $sd_log/update.log
echo "Current Version:  $VERSION" >> $sd_log/update.log
echo "Available Update: $UPDATE" >> $sd_log/update.log

# Compare versions
if update_version_newer "$UPDATE" "$VERSION"; then
    echo "Download Update: $UPDATE" >> $sd_log/update.log

        # Fetch latest version data
        $mkdir -p $sd_update
        HAVEDATA=$($curl_cmd -o $updatetgz "$UPDATE_URL/update-$UPDATE.tgz" >/dev/null 2>&1 && echo 1)

        if [ "$HAVEDATA" = "1" -a -f "$updatetgz" ]; then
                        $mkdir -p $sd_update
                        $tar -C $sd_update -xvzf $updatetgz >> $sd_log/update.log 2>&1
                        $rm -f $updatetgz
                        echo $UPDATE > $sd_etc/version.txt
                        echo "Update from $VERSION to $UPDATE extracted" >> $sd_log/update.log
                        [ -x "$sd_update/prepare.sh" ] && $sd_update/prepare.sh >> $sd_log/update.log
                        echo "Rebooting device" >> $sd_log/update.log
                        $touch /tmp/hostapd.reboot
        else
                echo "Error: Unable to fetch update data." >> $sd_log/update.log
                $rm -rf $sd_update
                $mv $sd_log/update.log $sd_log/update-error.log
                exit 2
        fi
else
    echo "No update needed. Already on the latest version." >> $sd_log/update.log
fi
