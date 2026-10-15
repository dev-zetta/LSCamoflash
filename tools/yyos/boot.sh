#!/bin/sh
# The normal YYOS hook runs this entry in the background, alongside stock boot.
set -eu
[ "$#" -eq 1 ] && [ "$1" = /mnt/sdcard ] || exit 2
BB=/mnt/sdcard/busybox
ROOT=/mnt/sdcard/LSCamoflash-yyos
for directory in /mnt /mnt/sdcard "$ROOT" "$ROOT/bin"; do
    [ -d "$directory" ] && [ ! -L "$directory" ] || exit 2
done
for file in "$ROOT/SHA256SUMS" "$ROOT/start.sh" "$ROOT/bin/busybox"; do
    [ -f "$file" ] && [ ! -L "$file" ] || exit 2
done
# The exact hardware, stock executable, mount and authentication guards are
# repeated by start.sh. No stock process or persistent setting is changed.
(cd "$ROOT" && "$BB" timeout -k 2 12 "$BB" sha256sum -c SHA256SUMS >/dev/null) || exit 1
exec "$BB" timeout -k 2 20 "$BB" sh "$ROOT/start.sh"
