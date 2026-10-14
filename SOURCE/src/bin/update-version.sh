#!/bin/bash
set -eu

VERSION_FILE="version.txt"
if [[ $# != 1 ]] || [[ $1 != --major && $1 != --minor && $1 != --revision ]]; then
    echo "Usage: $0 --major|--minor|--revision" >&2
    exit 2
fi
VERSION=$(cat "$VERSION_FILE")
if [[ ! $VERSION =~ ^([1-9][0-9]*)\.([0-9]{2})\.([0-9]{4})$ ]]; then
    echo "Version must have the form M.xx.xxxx, with a positive major and no leading zero" >&2
    exit 1
fi
MAJOR=${BASH_REMATCH[1]}
MINOR=$((10#${BASH_REMATCH[2]}))
REVISION=$((10#${BASH_REMATCH[3]}))

# Increment the decimal major as text, without a shell integer-size limit.
increment_major()
{
    local digits=$1 result= carry=1 digit
    while [[ -n $digits ]]; do
        digit=${digits: -1}
        digits=${digits%?}
        if [[ $carry == 1 ]]; then
            digit=$((digit + 1))
            if [[ $digit == 10 ]]; then digit=0; else carry=0; fi
        fi
        result=$digit$result
    done
    [[ $carry == 0 ]] || result=1$result
    printf '%s' "$result"
}

case $1 in
    --major) MAJOR=$(increment_major "$MAJOR"); MINOR=0; REVISION=0 ;;
    --minor)
        if [[ $MINOR == 99 ]]; then
            echo "Minor counter is full; use --major" >&2
            exit 1
        fi
        MINOR=$((MINOR + 1)); REVISION=0 ;;
    --revision)
        if [[ $REVISION == 9999 ]]; then
            echo "Revision counter is full; use --minor" >&2
            exit 1
        fi
        REVISION=$((REVISION + 1)) ;;
esac

printf -v NEW_VERSION '%s.%02d.%04d' "$MAJOR" "$MINOR" "$REVISION"
printf '%s\n' "$NEW_VERSION" > "$VERSION_FILE"
printf 'New version: %s\n' "$NEW_VERSION"
