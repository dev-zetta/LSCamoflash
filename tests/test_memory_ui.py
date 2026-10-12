"""Render the real system-info AJAX callback against fixture memory counters."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "SOURCE/src/sdcard/mmcblk0p2/HACK/var/www/js/lscamoflash.js").read_text()
FUNCTION = "function getSysinfo() {" + SOURCE.split("function getSysinfo() {", 1)[1].split("function fetchStreamURL()", 1)[0]


@unittest.skipUnless(shutil.which("node"), "Node.js is needed for the UI callback fixture")
class MemoryUiTests(unittest.TestCase):
    def render(self, memory):
        program = r'''
const vm = require("vm");
const fields = {};
let request;
const $ = selector => ({
    text(value) { (fields[selector] ||= {}).text = value; return this; },
    attr(name, value) { (fields[selector] ||= {})[name] = value; return this; },
    progressbar(name, value) { (fields[selector] ||= {})[name] = value; return this; }
});
$.ajax = options => { request = options; };
const context = {$, setTimeout() {}};
vm.runInNewContext(process.argv[1], context);
context.getSysinfo();
if (request.url !== "/cgi-bin/sysinfo.cgi") throw Error("Wrong status API");
request.success({memory: JSON.parse(process.argv[2]), cpu: {usage_percent: 0},
    load: {min1: 0, min5: 0, min15: 0},
    sdcard: {used: 0, size: 1, size_gb: "0", partition1: {used: 0, size: 1}, partition2: {used: 0, size: 1}}});
console.log(JSON.stringify(fields));
'''
        result = subprocess.run(["node", "-e", program, FUNCTION, json.dumps(memory)],
                                text=True, capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_available_memory_replaces_free_only_ninety_percent(self):
        fields = self.render({"total_kB": 65536, "free_kB": 6554, "available_kB": 32768,
                              "available_reported": True, "cached_kB": 24576,
                              "buffers_kB": 1024, "reclaimable_kB": 2048, "shared_kB": 4096})
        self.assertEqual(fields["#ram-percent"]["text"], 50)
        self.assertEqual(fields["#ram-progress"]["value"], 50)
        self.assertEqual(fields["#ram-label"]["text"], "RAM: used 32 MiB / 64 MiB (32 MiB available)")
        self.assertIn("cache (includes shared memory): 24 MiB", fields["#ram-label"]["title"])
        self.assertIn("shared/tmpfs: 4 MiB", fields["#ram-label"]["title"])
        self.assertIn("counters overlap", fields["#ram-label"]["title"])

    def test_real_zero_available_is_not_replaced_by_free_memory(self):
        fields = self.render({"total_kB": 65536, "free_kB": 8192, "available_kB": 0,
                              "available_reported": True})
        self.assertEqual(fields["#ram-percent"]["text"], 100)
        self.assertIn("0 MiB available", fields["#ram-label"]["text"])

    def test_missing_or_unreported_available_has_honest_free_fallback(self):
        for extra in ({}, {"available_kB": 0, "available_reported": False}, {"available_kB": "bad"}):
            with self.subTest(extra=extra):
                fields = self.render({"total_kB": 65536, "free_kB": 8192, **extra})
                self.assertEqual(fields["#ram-percent"]["text"], 88)
                self.assertEqual(fields["#ram-label"]["text"],
                                 "RAM: occupied 56 MiB / 64 MiB (free-memory fallback)")

    def test_zero_total_or_missing_counters_render_unavailable_without_nan(self):
        for memory in ({}, {"total_kB": 0, "free_kB": 0}, {"total_kB": 65536}):
            with self.subTest(memory=memory):
                fields = self.render(memory)
                self.assertEqual(fields["#ram-percent"]["text"], "-")
                self.assertEqual(fields["#ram-progress"]["value"], 0)
                self.assertEqual(fields["#ram-label"]["text"], "RAM: unavailable")
                self.assertNotIn("NaN", json.dumps(fields))

    def test_out_of_range_available_cannot_make_negative_usage(self):
        fields = self.render({"total_kB": 65536, "free_kB": 8192, "available_kB": 100000})
        self.assertEqual(fields["#ram-percent"]["text"], 0)
        self.assertEqual(fields["#ram-label"]["text"], "RAM: used 0 MiB / 64 MiB (64 MiB available)")


if __name__ == "__main__":
    unittest.main()
