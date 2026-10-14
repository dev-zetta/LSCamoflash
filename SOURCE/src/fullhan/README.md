# Fullhan read-only management pilot

This is a separate manual pilot for the exact LSC SZB22705 FW7.6.23 / FH8626V100 stock application. It leaves the stock camera application, RTSP server, networking, libraries and settings in place. It is not the Anyka installer or an automatic SD boot hook.

After a verified independent backup and explicit device-test approval, copy only the named LSCamoflash-fullhan folder to an already mounted FAT MMC partition at /mnt. The launcher expects /mnt/LSCamoflash-fullhan and the exact stock dgiot SHA256; it refuses other hardware, mounts and existing management state. Do not rename or replace a previous service directory to make validation pass.

Authentication is mandatory. There is no default password. Build with --password-file pointing to a private host file, or separately provision a regular httpd.conf before starting. A minimal configuration contains I:index.html and one /:username:MD5-crypt-hash rule. Arbitrary path/interpreter directives and plaintext passwords are rejected. Credentials stay outside www/ and are not part of the public source. Protect private host build outputs and the physical card. BusyBox HTTP uses Basic authentication over HTTP; keep this manual pilot on a trusted local network.

Start manually with /mnt/LSCamoflash-fullhan/bin/busybox sh /mnt/LSCamoflash-fullhan/start.sh. Open the camera's port 8080 and authenticate. The dashboard shows public model/firmware, current IP, uptime, RAM and the stock rtsp://camera-address:8554/main and /sub URLs. Both streams have verified H264 video; microphone audio is unverified. No settings, PTZ, reboot, update or recording deletion endpoint is supplied.

Stop with /mnt/LSCamoflash-fullhan/bin/busybox sh /mnt/LSCamoflash-fullhan/stop.sh. Only an HTTP process with the stored start time, exact executable and exact command line is signalled. The launcher does not overwrite an existing state directory. Fixed lifecycle messages are bounded in startup.log; HTTP requests and configuration contents are not logged. /tmp/lscamoflash-fullhan contains only the private PID state. Removing the pilot is not firmware restoration.

Project-authored pilot files are covered by LICENSE.MIT. The included static BusyBox is GPL version 2 only; COPYING.BusyBox is its original source LICENSE text. Its corresponding source archive, build configuration and patches are included with the project's public source release. Building or emulated tests do not establish physical Fullhan acceptance.
