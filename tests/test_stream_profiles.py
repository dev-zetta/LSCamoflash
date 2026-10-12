"""Exercise stream profiles with fixture interfaces, listeners, and routing only."""
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
HACK = ROOT / "SOURCE/src/sdcard/mmcblk0p2/HACK"
EXACT = {
    "device_rtsp_available": "1", "device_rtsp_main_port": "88",
    "device_rtsp_main_path": "/videoMain", "device_rtsp_sub_port": "89",
    "device_rtsp_sub_path": "/videoSub", "device_rtsp_main_width": "2304",
    "device_rtsp_main_height": "1296", "device_rtsp_sub_width": "640",
    "device_rtsp_sub_height": "360", "device_rtsp_main_codec": "H265",
    "device_rtsp_sub_codec": "H264",
}


def shell():
    return [str((ROOT / part).resolve()) if "/" in part and not part.startswith("-")
            else part for part in shlex.split(os.environ.get("CAMOFLASH_RUNTIME_SHELL", "sh"))]


class StreamTests(unittest.TestCase):
    def run_script(self, script, *, profile=None, ports=(554,), ip="192.0.2.8",
                   query="type=rtsp&source=local", connections="", credentials=False):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)
            for name in ("commands", "sbin", "etc", "config"):
                (path / name).mkdir()
            (path / "config/_ht_hw_settings.ini").write_text(
                "main_width = 1920\nmain_height = 1080\nsub_width = 640\nsub_height = 360\n")
            (path / "config/_ht_sw_settings.ini").write_text("bool_human_filter_enable = 0\n")
            (path / "config/wifimac.txt").write_text("fixture-hardware\n")
            if credentials:
                (path / "etc/onvif.users").write_text("ONVIF_USERNAME_0='fixture user'\nONVIF_PASSWORD_0='fixture password'\n")
            (path / "listeners").write_text("".join(
                f"tcp 0 0 0.0.0.0:{port} 0.0.0.0:* LISTEN\n" for port in ports))
            (path / "connections").write_text(connections)
            commands = {
                "ip": '#!/bin/sh\n[ -z "$TEST_IP" ] || printf "    inet %s/24 scope global wlan0\\n" "$TEST_IP"\n',
                "netstat": '#!/bin/sh\ncase "$1" in -tln) cat "$TEST_LISTENERS";; *) cat "$TEST_CONNECTIONS";; esac\n',
                "sleep": '#!/bin/sh\nexit 0\n',
                "date": '#!/bin/sh\necho 1700000000\n',
                "route": '#!/bin/sh\nif [ "$1" != -n ]; then printf "%s\\n" "$*" >> "$TEST_ROUTES"; : > "$TEST_CONNECTIONS"; fi\n',
            }
            for name, contents in commands.items():
                command = path / "commands" / name
                command.write_text(contents)
                command.chmod(0o755)
            server = path / "sbin/onvif_srvd"
            server.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$TEST_ARGS"\n')
            server.chmod(0o755)
            # Keep CGI response generation but omit hardware DB/session setup.
            (path / "common.cgi").write_text(
                'send_header() { printf "Content-Type: %s\\r\\n\\r\\n" "$1"; }\n')
            env = dict(os.environ, PATH=str(path / "commands") + os.pathsep + os.environ["PATH"],
                       TEST_IP=ip, TEST_LISTENERS=str(path / "listeners"),
                       TEST_CONNECTIONS=str(path / "connections"), TEST_ARGS=str(path / "args"),
                       TEST_ROUTES=str(path / "routes"), QUERY_STRING=query, hack=temporary,
                       sd_sbin=str(path / "sbin"), sd_etc=str(path / "etc"),
                       sys_config=str(path / "config"), sd_lib=temporary,
                       device_model="fixture camera", device_manufacturer="fixture",
                       device_version="fixture", anyka_md5="fixture", device_has_ptz="0",
                       hd_width="auto", hd_height="auto", port_onvif="5000", port_http="80",
                       port_ftp="21", port_telnet="23", offline_log=str(path / "offline.log"))
            for key in EXACT:
                env.pop(key, None)
            env.update(profile or {})
            # Target BusyBox ash can prefer built-in applets over PATH. Shell
            # functions take precedence too, keeping every network tool fake.
            stubs = "\n".join(f"{name}() {{ {shlex.quote(str(path / 'commands' / name))} \"$@\"; }}" for name in commands)
            invocation = stubs + "\n. " + shlex.quote(str(HACK / script))
            result = subprocess.run([*shell(), "-c", invocation], cwd=path, env=env,
                                    capture_output=True, text=True, timeout=5)
            return result, (path / "args").read_text().splitlines() if (path / "args").exists() else [], (path / "routes").read_text() if (path / "routes").exists() else ""

    def cgi(self, **kwargs):
        result, _, _ = self.run_script("var/www/cgi-bin/streamurl.cgi", **kwargs)
        return result, json.loads(result.stdout.strip().splitlines()[-1])

    def test_legacy_rtsp_url_is_preserved(self):
        result, body = self.cgi()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(body, {"url": "rtsp://192.0.2.8:554/main_ch", "type": "RTSP", "source": "LOCAL"})

    def test_exact_rtsp_uses_stock_endpoint(self):
        result, body = self.cgi(profile=EXACT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(body["url"], "rtsp://192.0.2.8:88/videoMain")

    def test_onvif_url_uses_configured_port(self):
        result, body = self.cgi(profile={"port_onvif": "6001"}, query="type=onvif&source=local")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(body["url"], "onvif://192.0.2.8:6001/")

    def test_normal_tuya_exact_profile_does_not_claim_rtsp(self):
        profile = dict(EXACT, device_rtsp_available="0")
        result, body = self.cgi(profile=profile)
        self.assertEqual(result.returncode, 1)
        self.assertIn("Status: 503", result.stdout)
        self.assertIn("not enabled", body["error"])
        result, args, _ = self.run_script("sbin/onvif.sh", profile=profile, ports=(88, 89))
        self.assertEqual(result.returncode, 1)
        self.assertEqual(args, [])

    def test_missing_address_fails_promptly(self):
        result, body = self.cgi(ip="")
        self.assertEqual(result.returncode, 1)
        self.assertIn("No local IPv4", body["error"])

    def test_invalid_profile_cannot_break_json(self):
        for profile in ({"device_rtsp_main_path": '/bad"path'}, {"device_rtsp_main_port": "70000"}):
            with self.subTest(profile=profile):
                result, body = self.cgi(profile=profile)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(body, {"error": "Invalid RTSP profile"})

    def test_invalid_query_returns_json_error(self):
        result, body = self.cgi(query='type=bad"type&source=local')
        self.assertEqual(result.returncode, 1)
        self.assertIn("Status: 400", result.stdout)
        self.assertEqual(body, {"error": "Invalid local stream type"})

    def test_legacy_onvif_keeps_single_hd_profile_and_credentials(self):
        result, args, _ = self.run_script("sbin/onvif.sh", credentials=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(args[args.index("--url") + 1], "rtsp://192.0.2.8:554/main_ch")
        self.assertEqual(args.count("--name"), 1)
        self.assertEqual(args[args.index("--width") + 1], "1920")
        self.assertEqual(args[args.index("--user") + 1], "fixture user")
        self.assertEqual(args[args.index("--password") + 1], "fixture password")

    def test_exact_onvif_only_advertises_supported_h264_substream(self):
        result, args, _ = self.run_script("sbin/onvif.sh", profile=EXACT, ports=(88, 89))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(args.count("--name"), 1)
        self.assertEqual(args[args.index("--name") + 1], "SD")
        self.assertEqual(args[args.index("--url") + 1], "rtsp://192.0.2.8:89/videoSub")
        self.assertEqual(args[args.index("--width") + 1], "640")
        self.assertEqual(args[args.index("--height") + 1], "360")
        self.assertEqual(args[args.index("--type") + 1], "H264")
        self.assertNotIn("H265", args)
        self.assertNotIn("--ptz", args)

    def test_h265_main_alone_does_not_produce_false_onvif_profile(self):
        result, args, _ = self.run_script("sbin/onvif.sh", profile=EXACT, ports=(88,))
        self.assertEqual(result.returncode, 1)
        self.assertEqual(args, [])

    def test_listener_port_matching_is_exact(self):
        result, args, _ = self.run_script("sbin/onvif.sh", profile=EXACT, ports=(888, 889))
        self.assertEqual(result.returncode, 1)
        self.assertEqual(args, [])

    def test_supported_main_and_sub_profiles_have_distinct_endpoints(self):
        result, args, _ = self.run_script("sbin/onvif.sh", profile=dict(EXACT, device_rtsp_main_codec="H264"), ports=(88, 89))
        self.assertEqual(result.returncode, 0, result.stderr)
        urls = [args[index + 1] for index, value in enumerate(args) if value == "--url"]
        self.assertEqual(urls, ["rtsp://192.0.2.8:88/videoMain", "rtsp://192.0.2.8:89/videoSub"])
        widths = [args[index + 1] for index, value in enumerate(args) if value == "--width"]
        self.assertEqual(widths, ["2304", "640"])

    def test_offline_mode_excludes_only_known_complete_rtsp_ports(self):
        for profile, port, blocked in ((None, 554, False), (EXACT, 88, False),
                                       (EXACT, 89, False), (EXACT, 888, True),
                                       (dict(EXACT, device_rtsp_available="0"), 88, True)):
            with self.subTest(port=port, available=profile):
                connection = f"tcp 0 0 192.0.2.8:{port} 203.0.113.10:30000 ESTABLISHED\n"
                result, _, routes = self.run_script("sbin/offline.sh", profile=profile, connections=connection)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(bool(routes), blocked)
                if blocked:
                    self.assertIn("add -net 203.0.113.10", routes)

    @unittest.skipUnless(shutil.which("node"), "Node.js is needed for the UI request fixture")
    def test_ui_requests_profile_url_and_displays_it_as_text(self):
        source = (HACK / "var/www/js/lscamoflash.js").read_text()
        function = source.split("function getLocalURL(urlType) {", 1)[1].split("function getRemoteURL", 1)[0]
        program = r'''
const vm = require("vm");
const assert = require("assert");
let request, buttons, displayed, copied;
const dialog = {dialog(value) { if (typeof value === "object") buttons=value.buttons; return this; },
                text(value) {displayed=value; return this;}};
const $ = () => dialog;
$.ajax = options => {request=options;};
const context = {$, copyToClipboard(value) {copied=value;}};
vm.runInNewContext(process.argv[1], context);
context.getLocalURL("RTSP");
assert.equal(request.url, "/cgi-bin/streamurl.cgi");
assert.equal(request.data.type, "RTSP");
assert.equal(request.data.source, "local");
request.success({url:"rtsp://192.0.2.8:88/videoMain"});
assert.equal(displayed, "rtsp://192.0.2.8:88/videoMain");
buttons["Copy link"]();
assert.equal(copied, displayed);
context.getLocalURL("ONVIF");
assert.equal(request.data.type, "ONVIF");
request.error({responseJSON:{error:"<fixture error>"}});
assert.equal(displayed, "<fixture error>");
'''
        result = subprocess.run(["node", "-e", program, "function getLocalURL(urlType) {" + function],
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn(":554/main_ch", source)


if __name__ == "__main__":
    unittest.main()
