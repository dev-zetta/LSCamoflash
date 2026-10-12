#!/bin/sh

root="/tmp/sd/HACK"

. ./common.cgi

export STREAM_TYPE=RTSP
export STREAM_SOURCE=LOCAL

TYPE=$(echo "$QUERY_STRING" | sed -n 's/.*type=\([^&]*\).*/\1/p')
SOURCE=$(echo "$QUERY_STRING" | sed -n 's/.*source=\([^&]*\).*/\1/p')

[ -n "$TYPE" ] && STREAM_TYPE=$TYPE
[ -n "$SOURCE" ] && STREAM_SOURCE=$SOURCE

stream_error()
{
    printf 'Status: %s\r\n' "$1"
    send_header application/json
    printf '{"error":"%s"}\n' "$2"
    exit 1
}
valid_endpoint()
{
    case "$1" in ''|*[!0-9]*) return 1;; esac
    [ "$1" -ge 1 ] && [ "$1" -le 65535 ] || return 1
    case "$2" in /*) ;; *) return 1;; esac
    case "$2" in *[!a-zA-Z0-9_./-]*) return 1;; esac
}

if [ "$STREAM_SOURCE" = "LOCAL" -o "$STREAM_SOURCE" = "local" ]; then
    [ "${device_rtsp_available:-1}" = "1" ] || stream_error "503 Service unavailable" "Local RTSP is not enabled for this firmware mode"
    IP_ADDR=$(ip -4 addr show wlan0 | awk '$1 == "inet" {split($2,a,"/"); print a[1]; exit}')
    case "$IP_ADDR" in ''|*[!0-9.]*) stream_error "503 Service unavailable" "No local IPv4 address";; esac
    STREAM_SOURCE="LOCAL"
    case "$STREAM_TYPE" in
        RTSP|rtsp)
            STREAM_TYPE=RTSP
            rtsp_port=${device_rtsp_main_port:-554}
            rtsp_path=${device_rtsp_main_path:-/main_ch}
            valid_endpoint "$rtsp_port" "$rtsp_path" || stream_error "503 Service unavailable" "Invalid RTSP profile"
            STREAM_ADDR="rtsp://$IP_ADDR:$rtsp_port$rtsp_path"
            ;;
        ONVIF|onvif)
            STREAM_TYPE=ONVIF
            onvif_port=${port_onvif:-5000}
            valid_endpoint "$onvif_port" / || stream_error "503 Service unavailable" "Invalid ONVIF profile"
            STREAM_ADDR="onvif://$IP_ADDR:$onvif_port/"
            ;;
        *)
            stream_error "400 Bad request" "Invalid local stream type"
            ;;
    esac
    # All interpolated fields above are enums or validated URL components.
    json="{\"url\":\"$STREAM_ADDR\",\"type\":\"$STREAM_TYPE\",\"source\":\"$STREAM_SOURCE\"}"
else
	STREAM_SOURCE="REMOTE"
	case $STREAM_TYPE in
		HLS|hls)
			STREAM_TYPE=HLS
			;;
		FLV|flv)
			STREAM_TYPE=FLV
			;;
		RTMP|rtmp)
			STREAM_TYPE=RTMP
			;;
		RTSP|rtsp)
			STREAM_TYPE=RTSP
			;;
		*)
			send_error 400 "Bad request" "Invalid remote stream type: $STREAM_TYPE"
			;;
	esac

	json=`/tmp/sd/HACK/sbin/get_stream_url.sh`
fi

if [ -n "$json" ]; then
	send_header application/json
	printf '%s\n' "$json"
else
	send_error 503 "Service unavailable" "No response from gateway script"
fi
