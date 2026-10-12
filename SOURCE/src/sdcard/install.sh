#!/bin/bash

# This installer can be sourced for offline tests; only main accesses devices.
is_block_device() {
	[[ -b "$1" ]]
}

die() {
	printf 'Fehler: %s\n' "$*" >&2
	exit 1
}

cleanup() {
	local failed=0 point
	[[ -n "${work_dir:-}" ]] || return 0
	for point in "$mount2" "$mount1"; do
		if mountpoint -q -- "$point"; then
			if ! umount -- "$point"; then
				printf 'Fehler: %s konnte nicht ausgehaengt werden.\n' "$point" >&2
				failed=1
			fi
		fi
	done
	# Never recursively delete a directory that might still contain a mounted card.
	if (( failed == 0 )); then
		rm -f -- "$backup/hack_custom.conf" "$backup/passwd" "$backup/shadow" "$backup/crontab"
		rmdir -- "$mount1" "$mount2" "$backup" "$work_dir" 2>/dev/null || true
	fi
	return "$failed"
}

unmount_device() {
	local status=0
	findmnt -rn -S "$1" >/dev/null || status=$?
	case "$status" in
		0) umount --all-targets -- "$1" ;;
		1) return 0 ;;
		*) die "Mount-Status fuer $1 konnte nicht ermittelt werden." ;;
	esac
}

# Reserve the initial alignment gap as well as a full 1 GiB second partition.
partition_layout() {
	local bytes="$1" mib=1048576 p1mib
	[[ "$bytes" =~ ^[0-9]+$ && ${#bytes} -lt 16 ]] || die "Ungueltige Datentraegergroesse."
	bytes=$(( 10#$bytes ))
	p1mib=$(( bytes / mib - 1024 - 1 ))
	(( p1mib >= 64 )) || die "Datentraeger ist fuer zwei FAT32-Partitionen zu klein."
	printf 'label: dos\nstart=1MiB, size=%sMiB, type=0c\nsize=1024MiB, type=0c\n' "$p1mib"
}

main() {
	set -Eeuo pipefail
	local use_sd_config=0 command disk device info kname kind removable readonly extra
	local name rm type details layout children child fstype confirmation source destination part
	local script_dir
	work_dir= mount1= mount2= backup=
	trap 'status=$?; trap - EXIT; cleanup || status=1; if (( status != 0 )); then printf "Installation abgebrochen (Status %s).\n" "$status" >&2; fi; exit "$status"' EXIT
	trap 'exit 130' INT
	trap 'exit 143' TERM

	while (( $# )); do
		case "$1" in
			-u|--use-sd-config) use_sd_config=1 ;;
			-h|--help) printf 'Aufruf: %s [-u|--use-sd-config]\n' "$0"; return 0 ;;
			*) die "Unbekanntes Argument: $1" ;;
		esac
		shift
	done
	[[ "$(id -u)" == 0 ]] || die "Bitte mit root-Rechten (sudo) starten."
	for command in lsblk blockdev findmnt mountpoint umount wipefs sfdisk partprobe udevadm mkfs.vfat mount cp sync mktemp mkdir rm rmdir dirname; do
		command -v "$command" >/dev/null || die "Benoetigtes Programm fehlt: $command"
	done
	script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
	[[ -d "$script_dir/mmcblk0p1" && -d "$script_dir/mmcblk0p2/HACK/etc" ]] || die "Installationsdateien fehlen neben install.sh."

	printf 'LSCamoflash SD-Karten Partitionierungsskript\n'
	printf 'ACHTUNG: ALLE DATEN AUF DEM GEWAEHLTEN DATENTRAEGER WERDEN GELOESCHT!\n'
	printf 'Verfuegbare Wechselmedien:\n'
	info=$(lsblk -dnro NAME,RM,TYPE,MODEL,SIZE)
	while read -r name rm type details; do
		if [[ "$rm" == 1 && "$type" == disk ]]; then
			printf '  %s %s\n' "$name" "$details"
		fi
	done <<< "$info"
	read -r -p 'Gib den Geraetenamen deiner SD-Karte ein (z.B. mmcblk0 oder sdb): ' disk
	# Accept a single kernel device name, never a path, option, symlink, or glob.
	[[ "$disk" =~ ^[a-zA-Z0-9][a-zA-Z0-9_.-]*$ ]] || die "Bitte genau einen Geraetenamen eingeben."
	device="/dev/$disk"
	[[ ! -L "$device" ]] && is_block_device "$device" || die "$device ist kein eindeutiges Blockgeraet."
	info=$(lsblk -dnro KNAME,TYPE,RM,RO "$device")
	[[ "$info" != *$'\n'* ]] || die "Mehrdeutiger Datentraeger."
	read -r kname kind removable readonly extra <<< "$info"
	[[ "$kname" == "$disk" && "$kind" == disk && "$removable" == 1 && "$readonly" == 0 && -z "$extra" ]] || die "Nur ganze, beschreibbare Wechselmedien (RM=1) sind erlaubt."

	case "$disk" in
		*[0-9]) part="${device}p" ;;
		*) part="$device" ;;
	esac
	layout=$(partition_layout "$(blockdev --getsize64 "$device")")
	children=$(lsblk -nrpo NAME,TYPE,FSTYPE "$device")
	# Refuse devices with active layered users (LVM, RAID, dm-crypt) or swap.
	while read -r child kind fstype extra; do
		[[ "$child" == /dev/* && -z "$extra" && "$fstype" != swap ]] || die "Unerwartete oder aktive Nutzung von $device."
		[[ "$kind" == part || ( "$child" == "$device" && "$kind" == disk ) ]] || die "Aktive Geraeteabhaengigkeit auf $device."
	done <<< "$children"
	read -r -p "Zum Loeschen von $device den Geraetenamen '$disk' erneut eingeben: " confirmation
	[[ "$confirmation" == "$disk" ]] || die "Datentraeger nicht bestaetigt."
	while read -r child kind fstype extra; do
		unmount_device "$child"
	done <<< "$children"

	work_dir=$(mktemp -d)
	mount1="$work_dir/partition1"
	mount2="$work_dir/partition2"
	backup="$work_dir/config"
	mkdir -- "$mount1" "$mount2" "$backup"
	if (( use_sd_config )); then
		for source in "${part}1" "${part}2"; do
			if is_block_device "$source"; then
				mount -o ro -- "$source" "$mount1"
				for destination in hack_custom.conf passwd shadow crontab; do
					case "$destination" in
						hack_custom.conf) name=HACK/etc/hack_custom.conf ;;
						passwd|shadow) name="HACK/etc/config/$destination" ;;
						crontab) name=HACK/var/spool/cron/crontabs/root ;;
					esac
					if [[ -f "$mount1/$name" ]]; then
						cp -f -- "$mount1/$name" "$backup/$destination"
					fi
				done
				umount -- "$mount1"
			fi
		done
	fi

	printf 'Loesche vorhandene Partitionen auf %s ...\n' "$device"
	wipefs --all --force "$device"
	printf 'Erstelle neue Partitionen...\n'
	sfdisk --wipe always --wipe-partitions always "$device" <<< "$layout"
	sync
	partprobe "$device"
	udevadm settle
	is_block_device "${part}1" && is_block_device "${part}2" || die "Neue Partitionen fehlen; Partitionstabelle wurde nicht neu eingelesen."
	unmount_device "${part}1"
	unmount_device "${part}2"
	printf 'Formatiere Partitionen als FAT32...\n'
	mkfs.vfat -F32 "${part}1"
	mkfs.vfat -F32 "${part}2"
	mount -- "${part}1" "$mount1"
	mount -- "${part}2" "$mount2"
	printf 'Kopiere Dateien auf die SD-Karte...\n'
	cp -R -- "$script_dir/mmcblk0p1/." "$mount1/"
	cp -R -- "$script_dir/mmcblk0p2/." "$mount2/"

	# Retain support for bundles that put account files directly in HACK/etc.
	for name in passwd shadow; do
		if [[ -f "$script_dir/mmcblk0p2/HACK/etc/$name" ]]; then
			cp -f -- "$script_dir/mmcblk0p2/HACK/etc/$name" "$mount1/$name"
		fi
	done

	# Existing local overrides are supported; a requested SD backup takes priority.
	for destination in hack_custom.conf passwd shadow crontab; do
		source="$script_dir/$destination"
		[[ ! -f "$backup/$destination" ]] || source="$backup/$destination"
		if [[ -f "$source" ]]; then
			case "$destination" in
				hack_custom.conf) cp -f -- "$source" "$mount2/HACK/etc/hack_custom.conf" ;;
				passwd|shadow)
					mkdir -p -- "$mount2/HACK/etc/config"
					cp -f -- "$source" "$mount1/$destination"
					cp -f -- "$source" "$mount2/HACK/etc/config/$destination"
					;;
				crontab)
					mkdir -p -- "$mount2/HACK/var/spool/cron/crontabs"
					cp -f -- "$source" "$mount2/HACK/var/spool/cron/crontabs/root"
					;;
			esac
		fi
	done
	printf 'Synchronisiere Dateisysteme...\n'
	sync
	umount -- "$mount2"
	umount -- "$mount1"
	cleanup
	work_dir=
	printf 'Partitionierung und Datenkopie abgeschlossen!\n'
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
	main "$@"
fi
