# Building and testing LSCamoflash

Build from source when you want to change the software or reproduce the packages. For camera setup, use the [installation guide](installation.md) and your camera's compatibility notes. Ready-made packages are available from the [fork's releases](https://github.com/dev-zetta/LSCamoflash/releases/latest).

The supported build path is an x86-64 Linux host cross-compiling the default ARM uClibc packages. The bundled toolchains run on x86-64 Linux; native Windows, macOS and ARM-host builds are not covered by this guide. The Makefile also contains glibc and musl options, but they are outside the validated default build and artifact checks.

Run the commands below from the repository root unless a command explicitly changes directories. Building and testing do not require a connected camera or SD card.

## Install the host tools

Use Python 3.11 or later for the build verifier and development tests. On Ubuntu or a compatible Debian-based system, install the build tools, archive utilities and test dependencies:

```sh
sudo apt-get update
sudo apt-get install -y \
  git git-lfs ca-certificates curl unzip tar gzip bzip2 xz-utils \
  build-essential binutils make cmake flex bison gsoap \
  automake autoconf autoconf-archive pkg-config perl patch \
  python3 busybox fdisk qemu-user openssl nodejs
```

The compiler and GNU build tools compile the bundled projects. The host `gsoap` package supplies the SOAP code generators used by ONVIF; the build also cross-compiles the camera's gSOAP library. `curl` and the archive utilities fetch and unpack source inputs. `busybox` and `fdisk` support host regression fixtures, while `qemu-user` provides `qemu-arm` for running ARM userspace checks without hardware. Host OpenSSL hashes private dashboard credentials, and Node.js runs the browser behavior fixtures without npm packages.

The [Build-Test workflow](../.github/workflows/makefile.yml) is the reference for the current CI environment and build steps. It runs on GitHub's Ubuntu image, where some common utilities are already installed; the command above lists those utilities explicitly for a fresh host.

## Clone the fork and fetch its sources

```sh
git clone https://github.com/dev-zetta/LSCamoflash.git
cd LSCamoflash
git lfs install --local
git lfs pull
```

Git LFS stores the source archives under `SOURCE/download/`. Fetching them explicitly avoids building with small LFS pointer files in place of archives. The Makefile also has a download fallback that replaces pointers and checks their recorded SHA-256 hashes. Keep network access available until the required inputs have been fetched.

## Build the default packages

To build the camera runtime, the separate firmware backup kit, and both runtime archives in the same order as CI:

```sh
make -C SOURCE nproc=8 all backup-kit release update
```

Set `nproc` to the number of package compilation jobs your host can support. The top-level build phases run in order; individual packages use this job limit. Run the build as your normal user.

For the runtime alone, use `make -C SOURCE all`. Add `release`, `update` or `backup-kit` when you need the corresponding output. Here, `release` creates a local archive; it does not publish a GitHub release or write to a card.

| Output | Purpose |
| --- | --- |
| `SOURCE/build/` | Generated runtime card contents, with `mmcblk0p1/`, `mmcblk0p2/`, `install.sh` and `install.ps1`. |
| `SOURCE/LSCamoflash-<version>-uclibc.tar.gz` | Full runtime package containing the build tree and installers. |
| `SOURCE/update-<version>-uclibc.tgz` | Runtime update package; excludes `HACK/etc/` and the local root crontab to preserve camera configuration. |
| `SOURCE/backup-kit/` | Separate backup kit, including its `card/` payload, verifier, manifest and checksums. |

`<version>` comes from `SOURCE/version.txt`; inspect it with `make -C SOURCE version`. The default build includes FFmpeg and PHP. Optional kernel, Python and radare2 builds are disabled by default; enabling them is a separate development configuration.

Use the [firmware backup guide](firmware-backup.md) for the kit's staging procedure. Its boot markers must stay separate from a runtime installation. A completed build does not select the correct card layout or firmware profile for your camera.

## Build the separate Fullhan pilot

The [SZ B22705 / firmware 7.6.23 pilot](camera-sz-b22705.md) has a manually started management interface, bounded read-only recording downloads and an optional isolated ONVIF service. It has its own package and does not use the Anyka runtime, installer or SD bootstrap. The richer interface and optional services require their own device acceptance; an earlier status-only pilot passed short live checks.

To build the static ONVIF candidate and include it in a credential-free Fullhan payload, run from the repository root:

```sh
QEMU_ARM=/usr/bin/qemu-arm make -C SOURCE fullhan-busybox-kit fullhan-onvif-kit fullhan-kit \
  FULLHAN_ONVIF_KIT="$PWD/SOURCE/fullhan-onvif"
```

The separate BusyBox build produces `SOURCE/fullhan-busybox/bin/busybox` with the Fullhan HTTP Range-to-CGI patch. A live request found that the shared BusyBox 1.36.1 consumed the Range header before invoking CGI; this isolated build forwards it for recording seeking/resume without changing the stock or Anyka binaries. The ONVIF build produces `SOURCE/fullhan-onvif/`, including the static server, provenance manifest and `COPYING.ONVIF`. The assembled management payload is `SOURCE/fullhan-kit/LSCamoflash-fullhan/`, including the recording helper, web assets and optional ONVIF launchers. The ONVIF and assembled-payload builders require an absent or empty destination and refuse to overwrite existing files. Preserve earlier outputs and site credentials before preparing a replacement; do not rerun the command over a nonempty build directory.

For the dashboard and recording browser without the optional ONVIF service, choose `QEMU_ARM=/usr/bin/qemu-arm make -C SOURCE fullhan-busybox-kit fullhan-kit` instead. The default payload cannot start until dashboard credentials are provisioned. The ONVIF service separately requires its own private credentials and endpoint UUID.

Create two separate private host files, each containing one password line, then build a private copy in a new output directory:

```sh
python3 tools/fullhan/build-kit.py \
  --qemu /usr/bin/qemu-arm \
  --busybox SOURCE/fullhan-busybox/bin/busybox \
  --onvif-kit SOURCE/fullhan-onvif \
  --password-file /absolute/private/path/dashboard-password.txt \
  --onvif-password-file /absolute/private/path/onvif-password.txt \
  --output /absolute/private/path/LSCamoflash-fullhan
```

Omit both `--onvif-kit` and `--onvif-password-file` for a dashboard-only copy. The username defaults to `admin` for both provisioned accounts and can be changed with `--username`; use independent passwords. Host OpenSSL receives the dashboard password through stdin and writes only its salted MD5-crypt hash to `httpd.conf`. The ONVIF password must be one printable ASCII line of 1–128 bytes. ONVIF uses a separate two-line `onvif.auth` containing its username and plaintext password for WSSE UsernameToken / HTTP Digest authentication, plus a private UUIDv4 in `onvif.uuid` identifying the endpoint.

Independent ONVIF credentials remain mandatory for service startup. The only anonymous ONVIF operation is the read-only `GetSystemDateAndTime` query, which lets clients synchronize WSSE authentication timestamps with the camera’s clock. Device capabilities and media information still require WSSE UsernameToken or HTTP Digest authentication. Timestamp and replay checks remain enforced; this exception does not change the camera’s clock or settings.

`httpd.conf`, `onvif.auth` and `onvif.uuid` stay outside the served `www/` directory and are excluded from the public payload checksum list. Keep these site-owned files and all private output copies out of the repository and published artifacts. Preserve the existing ONVIF credentials and UUID when replacing a stopped installation so clients retain the same endpoint identity; the builder generates a fresh UUID for a newly provisioned copy.

The builder checks static ARM ELF attributes, includes license notices and records public payload checksums. `--qemu` also verifies BusyBox applets, HTTP authentication support and helper invalid-input behavior under ARM1176. The optional ONVIF build records its source inputs and patch provenance. Neither builder installs files on a camera. CI is configured to publish a separate credential-free experimental Fullhan artifact; it is separate from the eight stable release assets.

Follow the [camera guide](camera-sz-b22705.md#experimental-fullhan-management-interface) for placement, mandatory authentication, separate manual HTTP/ONVIF start and stop commands, and acceptance limits. Each camera reboot still requires `start.sh` and, if ONVIF is used, `onvif-start.sh --no-discovery` to be started manually. This unit’s stock application owns UDP 3702; the new authenticated service uses manual client setup at port 5000 and leaves stock discovery untouched.

## Verify the generated runtime

After generating both runtime archives, run:

```sh
python3 SOURCE/src/bin/verify-build.py \
  --output .local/logs/artifact-verification.json
```

The verifier checks that the packaged files match the source templates and version, rejects non-ARM ELF binaries, runs packaged programs under QEMU, checks the ARM926 bootstrap and RTSP helper, and compares the full and update archives against the build tree. It also confirms that the update archive excludes configuration files and the local crontab. A nonzero exit status means the build should not be distributed.

These checks exercise packaging and userspace behavior. Camera Wi-Fi, streaming, audio, motor control and installation still need testing on the exact hardware and stock firmware.

## Run the regression tests

Run the host tests before or after building:

```sh
python3 -m unittest discover -s tests -v
```

The host suite uses temporary files and simulated services to cover installers, startup, networking, firmware backup, streaming callbacks, updates and the web interface. Tests that need the ARM compiler or ARM BusyBox are skipped unless their environment variables are supplied.

After the default build, use the same ARM926 fixture configuration as CI to enable those additional checks:

```sh
CAMOFLASH_RUNTIME_SHELL="/usr/bin/qemu-arm -cpu arm926 $PWD/SOURCE/build/mmcblk0p2/HACK/bin/busybox ash" \
BACKUP_ARM_CC="$PWD/SOURCE/toolchain/uclibc/bin/arm-buildroot-linux-uclibcgnueabi-gcc" \
BACKUP_ARM_BUSYBOX="$PWD/SOURCE/build/mmcblk0p2/HACK/bin/busybox" \
BACKUP_QEMU=/usr/bin/qemu-arm \
python3 -m unittest discover -s tests -v
```

If `qemu-arm` is installed elsewhere, replace both `/usr/bin/qemu-arm` paths with its absolute path. Use a checkout path without spaces for this shell-command configuration. The fixtures do not read a camera's flash or establish device acceptance.

To run a focused subset, select its test file. For example, the standalone backup tests can be run with:

```sh
python3 -m unittest discover -s tests -p 'test_firmware_backup*.py' -v
```

## Rebuild after changes

Runtime templates live under `SOURCE/src/sdcard/`, the isolated Fullhan pilot under `SOURCE/src/fullhan/`, native helpers under `SOURCE/src/contrib/`, and third-party build patches under `SOURCE/src/patches/`. Generated packages, toolchains, staging files and card contents are kept separately under `SOURCE/`.

For a clean rebuild after changing package configuration or patches:

```sh
make -C SOURCE mrproper
make -C SOURCE nproc=8 all backup-kit release update
```

`mrproper` removes the generated packages, toolchains, host tools, staging tree, build tree and runtime archives; it keeps the downloaded source inputs. Keep any local work outside those generated directories. `mrproper-full` also removes `SOURCE/download/` and forces the source inputs to be fetched again.

## Prepare assets for a release

After the build verifier and regression tests pass, stage the public assets in a dedicated absent or empty directory:

```sh
python3 SOURCE/src/bin/prepare-release.py --output release
cd release
sha256sum --strict --check SHA256SUMS
```

This produces the versioned runtime archives, a packaged backup kit, a public source bundle, license notices and `SHA256SUMS`. The source bundle includes tracked public files and hydrated declared build inputs; it excludes private `.local/` data and untracked files. The helper checks archive consistency and source input hashes, but does not run the build or its runtime verifier for you. It refuses to replace a nonempty output directory.

See the [release guide](release.md) for published packages and release information, the [changelog](../CHANGELOG.md) for changes, and the [third-party notices](../SOURCE/3RD_PARTY_LICENSES.md) for bundled components and their source/license requirements.

## Publish a GitHub release

Publishing is a separate maintainer step with repository write access. The [Publish Release workflow](../.github/workflows/release.yml) publishes the assets from a successful CI build; it does not rebuild them on the release runner.

1. Set the next version in `SOURCE/version.txt`, using the required `1.xx.xxxx` format. For a revision bump, run `make -C SOURCE update-version-revision`. Add a matching `## [<version>]` entry with the release date and changes to `CHANGELOG.md`.
2. Review and commit the version, changelog and public source changes, then push the release commit to `main`. Keep firmware dumps, credentials, card contents and private logs out of the commit.
3. Wait for **Build-Test**, **Shell regressions** and **CodeQL Advanced** to succeed for that exact commit. Record the successful Build-Test run ID from its Actions URL. The release gate requires a completed successful run of `makefile.yml` in this repository, from a trusted push or manual dispatch, with the same commit SHA as the release workflow. If the validated release artifact has expired, rerun Build-Test for that commit.
4. In the fork's **Actions → Publish Release → Run workflow**, select `main` and enter the Build-Test run ID in `build_run_id`. Confirm that `main` still points to the validated commit. Alternatively, use an authenticated GitHub CLI:

   ```sh
   BUILD_RUN_ID="<successful-build-run-id>"
   gh workflow run release.yml \
     --repo dev-zetta/LSCamoflash --ref main \
     -f build_run_id="$BUILD_RUN_ID"
   ```

5. Wait for the publishing run to finish successfully. Confirm that the new `v<version>` tag points to the validated commit, the release contains all eight expected assets, and the downloaded assets pass `sha256sum --strict --check SHA256SUMS` when collected together. The seven checksummed files are the full runtime, update, backup kit, source bundle, `LICENSE.MIT`, `COPYING.BusyBox` and `THIRD_PARTY_NOTICES.md`; `SHA256SUMS` is the eighth asset.

The workflow checks the CI artifact's SHA-256 manifest, refuses an existing version tag, and creates the release at the validated commit using `CHANGELOG.md` as its notes. The Build-Test match is enforced by the workflow; waiting for the other checks remains part of the maintainer procedure. Fix a failed run before treating the release as published, and use a new version for a later release rather than replacing an existing tag.
