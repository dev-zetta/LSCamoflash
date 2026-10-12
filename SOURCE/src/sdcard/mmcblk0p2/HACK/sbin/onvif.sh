#!/bin/sh

[ -n "$hack" ] || exit 1
[ "${device_rtsp_available:-1}" = "1" ] || exit 1
cd "$sd_sbin" || exit 1

valid_endpoint()
{
    case "$1" in ''|*[!0-9]*) return 1;; esac
    [ "$1" -ge 1 ] && [ "$1" -le 65535 ] || return 1
    case "$2" in /*) ;; *) return 1;; esac
    case "$2" in *[!a-zA-Z0-9_./-]*) return 1;; esac
}

rtsp_main_port=${device_rtsp_main_port:-554}
rtsp_main_path=${device_rtsp_main_path:-/main_ch}
rtsp_sub_port=${device_rtsp_sub_port:-554}
rtsp_sub_path=${device_rtsp_sub_path:-/sub_ch}
valid_endpoint "$rtsp_main_port" "$rtsp_main_path" || exit 1
valid_endpoint "$rtsp_sub_port" "$rtsp_sub_path" || exit 1

IP_ADDR=$(ip -4 addr show wlan0 | awk '$1 == "inet" {split($2,a,"/"); print a[1]; exit}')
[ -n "$IP_ADDR" ] || exit 1

hw_setting()
{
    awk -F= -v key="$1" '$1 ~ "^[[:space:]]*" key "[[:space:]]*$" {gsub(/[[:space:]]/,"",$2); print $2; exit}' "$sys_config/_ht_hw_settings.ini" 2>/dev/null
}
if [ -n "${device_rtsp_main_width:-}" ]; then
    hd_width=$device_rtsp_main_width
    hd_height=$device_rtsp_main_height
else
    [ "${hd_width:-auto}" != "auto" ] || hd_width=$(hw_setting main_width)
    [ "${hd_height:-auto}" != "auto" ] || hd_height=$(hw_setting main_height)
fi
hd_width=${hd_width:-${device_width:-1920}}
hd_height=${hd_height:-${device_height:-1080}}
encoder_main=${device_rtsp_main_codec:-H264}
encoder_sub=${device_rtsp_sub_codec:-H264}

ONVIF_SNAP_TOKEN=""
[ ! -f "$sd_etc/onvif.token" ] || ONVIF_SNAP_TOKEN=$(cat "$sd_etc/onvif.token")
[ ! -f "$sd_etc/onvif.users" ] || . "$sd_etc/onvif.users"
HARDWARE_ID=$(cat "$sys_config/wifimac.txt" 2>/dev/null)
set -- --no_fork --pid_file /var/run/onvif_srvd.pid \
    --model "$device_model" --manufacturer "$device_manufacturer" --ifs wlan0 --port "$port_onvif" \
    --scope onvif://www.onvif.org/Profile/S --firmware_ver "LSCamoflash $device_version" \
    --hardware_id "$HARDWARE_ID" --serial_num "$anyka_md5" \
    --user "${ONVIF_USERNAME_0:-admin}" --password "${ONVIF_PASSWORD_0:-admin}"

human_filter_enable=$(awk -F= '$1 ~ /^[[:space:]]*bool_human_filter_enable[[:space:]]*$/ {gsub(/[[:space:]]/,"",$2); print $2; exit}' "$sys_config/_ht_sw_settings.ini" 2>/dev/null)
if [ "$human_filter_enable" = "1" ]; then
    set -- "$@" --snapurl "http://$IP_ADDR:$port_http/cgi-bin/snapshot.cgi?token=$ONVIF_SNAP_TOKEN"
fi
if [ "$device_has_ptz" = "1" ]; then
    set -- "$@" --ptz \
        --move_left "eval $sd_sbin/ptz.sh left 15" --move_right "eval $sd_sbin/ptz.sh right 15" \
        --move_up "eval $sd_sbin/ptz.sh up 15" --move_down "eval $sd_sbin/ptz.sh down 15"
fi

rtsp_listening()
{
    netstat -tln 2>/dev/null | awk -v port="$1" -v ip="$IP_ADDR" \
        '$1 == "tcp" && $6 == "LISTEN" && ($4 == "0.0.0.0:" port || $4 == ip ":" port) {found=1} END {exit !found}'
}
profile_count=0
# onvif_srvd supports JPEG/MPEG4/H264 only. Do not advertise the exact .125
# firmware's H265 main stream as H264; its separate H264 substream is usable.
case "$encoder_main" in JPEG|MPEG4|H264)
    if rtsp_listening "$rtsp_main_port"; then
        set -- "$@" --name HD --width "$hd_width" --height "$hd_height" \
            --url "rtsp://$IP_ADDR:$rtsp_main_port$rtsp_main_path" --type "$encoder_main"
        profile_count=$((profile_count + 1))
    fi
esac
# Existing profiles keep their single main stream. A firmware profile opts into
# a separate substream by supplying its verified dimensions.
if [ -n "${device_rtsp_sub_width:-}" ] && [ -n "${device_rtsp_sub_height:-}" ]; then
    case "$encoder_sub" in JPEG|MPEG4|H264)
        if rtsp_listening "$rtsp_sub_port"; then
            set -- "$@" --name SD --width "$device_rtsp_sub_width" --height "$device_rtsp_sub_height" \
                --url "rtsp://$IP_ADDR:$rtsp_sub_port$rtsp_sub_path" --type "$encoder_sub"
            profile_count=$((profile_count + 1))
        fi
    esac
fi
if [ "$profile_count" -eq 0 ]; then
    sleep 10
    exit 1
fi
LD_LIBRARY_PATH="$sd_lib:/lib:/usr/lib" "$sd_sbin/onvif_srvd" "$@"
