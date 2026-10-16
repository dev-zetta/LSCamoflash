# Optional YYOS SSH runtime

Experimental, exact-profile root administration for LSC3225722 / SZ F26312 / V14.1.5 / AK3918AV130. The static ARMv5 Dropbear server uses Ed25519 public-key authentication on one private IPv4 address, TCP2222. Password authentication, forwarding and SFTP are compiled out. Camera SSH authentication, memory use and cold-boot acceptance must be verified separately; packaging or QEMU success is not device acceptance.

The site-owned authorized_keys must be one bare Ed25519 public-key line, dropbear_ed25519_host_key an 83-byte native Dropbear Ed25519 key, and ssh.enabled exactly enabled followed by a newline. These three files are deliberately outside public checksums and are validated independently. Never publish this private kit. Start checks the stock identity, trusted writable MMC/VFAT mount and exact public inventory, then copies keys into root-owned protected RAM with mode0600. It changes no stock passwords, configuration, application, network routes or startup files.

Manual start and stop use the static bin/busybox shell. The normal SD hook may invoke start.sh through the separately guarded boot composition. Do not use or live-change yy_debug.ini. The root telnetd filename remains the project's native launcher, not a shell daemon. HTTP management stays independent and stock startup is never invoked by this runtime.

Only the owned PID/start time/address/listener is accepted. Stop refuses unrelated PIDs and active SSH child sessions; close sessions first. Removing ssh.enabled while powered off prevents the next SSH startup but does not terminate an existing daemon. SSH grants a root shell, whose commands can change the camera beyond the read-only HTTP dashboard. Protect and pin the host key and keep the owner's client private key on the host.

LICENSE.MIT covers project code; COPYING.BusyBox and COPYING.Dropbear retain component notices. Preserve corresponding source/configuration and static toolchain runtime licensing/relink materials before redistributing binaries. The matching public source tree's docs/yyos-ssh.md describes packaging, guarded staging and acceptance.
