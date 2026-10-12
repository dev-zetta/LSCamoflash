#!/bin/sh
# Hydrate Git LFS pointers without requiring a global git-lfs installation.
set -eu
url=$1
destination=$2
expected=
if [ -s "$destination" ]; then
    if ! head -n 1 "$destination" | grep -qx 'version https://git-lfs.github.com/spec/v1'; then
        exit 0
    fi
    expected=$(awk '/^oid sha256:/ { sub(/^sha256:/, "", $2); print $2 }' "$destination")
    if [ "${#expected}" -ne 64 ]; then
        echo "Invalid Git LFS pointer: $destination" >&2
        exit 1
    fi
fi
mkdir -p "$(dirname "$destination")"
temporary=$(mktemp "$destination.XXXXXX")
trap 'rm -f "$temporary"' EXIT HUP INT TERM
printf 'Downloading %s...\n' "$(basename "$destination")"
curl --fail --location --retry 3 --output "$temporary" "$url"
if [ -n "$expected" ]; then
    printf '%s  %s\n' "$expected" "$temporary" | sha256sum --check -
fi
if head -n 1 "$temporary" | grep -qx 'version https://git-lfs.github.com/spec/v1'; then
    echo "Server returned a Git LFS pointer instead of an archive: $url" >&2
    exit 1
fi
if [ ! -s "$temporary" ]; then
    echo "Server returned an empty download: $url" >&2
    exit 1
fi
mv "$temporary" "$destination"
