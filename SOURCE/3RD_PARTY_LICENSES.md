# License Information

Project: LSCamoflash
URL: https://github.com/dev-zetta/LSCamoflash
License: see LICENSE.MIT

This project includes various third-party software packages, each with its own licensing terms. Below is a list of included packages and their respective licenses. Please ensure compliance with the licensing terms when redistributing or modifying this software.

---

## Release artifacts and source

The project license applies to project-authored code. Third-party components keep their own licenses; the full runtime, backup kit and source bundle must not be described as wholly MIT licensed. Which optional components are included depends on the SOURCE/Makefile build options.

`SOURCE/src/bin/prepare-release.py --output release` stages the versioned full and update archives, a separate backup-kit archive, LICENSE.MIT, COPYING.BusyBox, THIRD_PARTY_NOTICES.md, SHA256SUMS and a public source bundle. The source bundle contains Git-tracked public files, including build scripts, configurations and patches, plus all hydrated archives and other inputs declared in SOURCE/Makefile URLS. Private research, untracked extracted files and undeclared downloads are excluded. Each upstream source archive retains its license texts.

The separate experimental Fullhan pilot contains project-authored scripts and a static BusyBox, with LICENSE.MIT and COPYING.BusyBox included in its own output. Its BusyBox source, configuration and patches use the same declared inputs as the default build. Site-owned authentication and proprietary Fullhan firmware are excluded from public packages.

## Toolchains

The Bootlin 2020.08-1 uClibc, glibc and musl toolchains contain components under several licenses, rather than one GPLv2 license. The uClibc toolchain README.txt identifies, among others, GPLv3+ binutils, LGPL-2.1+ uClibc-ng, GPLv2 Linux headers, and differently licensed host tools. GCC and its runtime libraries also carry component-specific terms and runtime exceptions; consult their original notices.

The archived toolchains are prebuilt distributions, not complete compiler or C-library source bundles. Bootlin publishes separate [component sources](https://toolchains.bootlin.com/downloads/releases/sources/) and [license information](https://toolchains.bootlin.com/downloads/releases/licenses/). Their README.txt gives the rebuild repository [bootlin/buildroot-toolchains](https://github.com/bootlin/buildroot-toolchains), tag `toolchains.bootlin.com-2020.08-1`, and the matching architecture/libc build fragment. These external source and license catalogs are not mirrored by the release preparer. See [Bootlin's toolchain documentation](https://toolchains.bootlin.com/).

## JavaScript
- **Bootstrap (5.x)**  
  Lizenz: MIT License  
  Quelle: [https://getbootstrap.com](https://getbootstrap.com)  

- **jQuery (3.x)**  
  Lizenz: MIT License  
  Quelle: [https://jquery.com](https://jquery.com)

## Kernel
- **Linux Kernel (4.4.192)**  
  Lizenz: GNU General Public License (GPL)  
  Quelle: [https://www.kernel.org](https://www.kernel.org)

## Libraries
- **libpcap (1.10.4)**  
  Lizenz: BSD License  
  Quelle: [https://www.tcpdump.org](https://www.tcpdump.org)

- **OpenSSL (3.0.12)**  
  Lizenz: Apache License 2.0  
  Quelle: [https://www.openssl.org](https://www.openssl.org)

- **zlib (1.3.1)**  
  Lizenz: zlib License  
  Quelle: [http://www.zlib.net](http://www.zlib.net)

- **glibc (2.32)**  
  Lizenz: GNU Lesser General Public License (LGPL)  
  Quelle: [https://www.gnu.org/software/libc/](https://www.gnu.org/software/libc/)

- **GMP (6.3.0)**  
  Lizenz: GNU Lesser General Public License (LGPL)  
  Quelle: [https://gmplib.org](https://gmplib.org)

- **libexecinfo (1.1-rc2)**
  Lizenz: BSD License  
  Quelle: [https://www.freshports.org/devel/libexecinfo/](https://www.freshports.org/devel/libexecinfo/)

- **libgcrypt (1.11.0)**  
  Lizenz: GNU Lesser General Public License (LGPL)  
  Quelle: [https://gnupg.org/software/libgcrypt/](https://gnupg.org/software/libgcrypt/)

- **libgpg-error (1.51)**  
  Lizenz: GNU Lesser General Public License (LGPL)  
  Quelle: [https://gnupg.org/software/libgpg-error/](https://gnupg.org/software/libgpg-error/)

- **libilbc (3.0.4)**  
  Lizenz: BSD License  
  Quelle: [https://github.com/TimothyGu/libilbc](https://github.com/TimothyGu/libilbc)

- **OpenJPEG (2.5.3)**  
  Lizenz: BSD License  
  Quelle: [https://www.openjpeg.org](https://www.openjpeg.org)

- **Opus (1.5.2)**  
  Lizenz: BSD License  
  Quelle: [https://opus-codec.org](https://opus-codec.org)

- **cJSON (1.7.18)**  
  Lizenz: MIT License  
  Quelle: [https://github.com/DaveGamble/cJSON](https://github.com/DaveGamble/cJSON)

- **gSOAP (2.8)**  
  Lizenz: GNU General Public License (GPL)  
  Quelle: [https://www.genivia.com/products/gsoap/](https://www.genivia.com/products/gsoap/)

## Utilities
- **BusyBox (1.36.1)**
  License: GNU General Public License version 2 only (GPLv2-only). The source archive's LICENSE contains the notice and license text; the release preparer includes those exact bytes as COPYING.BusyBox. The repository includes its build configuration and patches.
  Source and license: [BusyBox](https://busybox.net/license.html)

- **php (8.4.4)**  
  Lizenz: PHP-License Version 3.01
  Quelle: [https://www.php.net](https://www.php.net)

- **python (3.13.2)**  
  Lizenz: Python Software Foundation License
  Quelle: [https://www.python.org](https://www.python.org)

- **sqlite (3.45.2)**  
  Lizenz: Public Domain  
  Quelle: [https://www.sqlite.org](https://www.sqlite.org)

- **sqlcipher (4.5.5)**  
  Lizenz: BSD License  
  Quelle: [https://github.com/sqlcipher/sqlcipher](https://github.com/sqlcipher/sqlcipher)

- **cURL (8.7.1)**  
  Lizenz: MIT License  
  Quelle: [https://curl.se](https://curl.se)

- **FFmpeg (7.1)**  
  License for this build: GNU General Public License version 3 or later (GPLv3+). The recipe enables both `--enable-gpl` and `--enable-version3`; see the source archive's LICENSE.md and COPYING.GPLv3, and [FFmpeg license documentation](https://ffmpeg.org/legal.html).
  Source: [https://ffmpeg.org](https://ffmpeg.org)

- **Joe's Own Editor (4.6)**  
  Lizenz: GNU General Public License (GPL)  
  Quelle: [http://joe-editor.sourceforge.net](http://joe-editor.sourceforge.net)

- **miniupnpc (2.3.0)**  
  Lizenz: BSD License  
  Quelle: [https://miniupnp.tuxfamily.org](https://miniupnp.tuxfamily.org)

- **Mosquitto (2.0.20)**  
  Lizenz: Eclipse Public License 2.0  
  Quelle: [https://mosquitto.org](https://mosquitto.org)

- **msmtp (1.8.24)**  
  Lizenz: GNU General Public License (GPL)  
  Quelle: [https://marlam.de/msmtp/](https://marlam.de/msmtp/)

- **onvif_srvd (2.0)**
  Lizenz: GNU General Public License (GPL)  
  Quelle: [https://github.com/KoynovStas/onvif_srvd](https://github.com/KoynovStas/onvif_srvd)

- **radare2 (5.9.8)**  
  Lizenz: GNU General Public License (GPL)  
  Quelle: [https://rada.re/n/radare2.html](https://rada.re/n/radare2.html)

- **strace (6.9)**  
  License: GNU Lesser General Public License version 2.1 or later (LGPL-2.1+), as stated in the source COPYING file. Its test suite and bundled Linux headers have separate terms.
  Quelle: [https://strace.io](https://strace.io)

- **tcpdump (4.99.4)**  
  Lizenz: BSD License  
  Quelle: [https://www.tcpdump.org](https://www.tcpdump.org)

## Python modules
- **zeroconf (0.146.1)**  
  Lizenz: GNU Lesser General Public License (LGPL)
  Quelle: [https://github.com/python-zeroconf/python-zeroconf](https://github.com/python-zeroconf/python-zeroconf)

- **flask (3.1.0)**  
  Lizenz: BSD-3-Clause License  
  Quelle: [https://github.com/pallets/flask](https://github.com/pallets/flask)

## Cryptographic Functions
- **MD5 & SHA1 Implementations** (from GNU Coreutils)  
  License: GNU General Public License (GPLv3)
  Source: https://raw.githubusercontent.com/coreutils/gnulib

## Eclipse Mosquitto
- **Mosquitto** (2.0.20)  
  License: Eclipse Public License 2.0 and the Eclipse Distribution License 1.0
  Source: https://github.com/eclipse-mosquitto/mosquitto/blob/master/LICENSE.txt
  EPL-V20: https://github.com/eclipse-mosquitto/mosquitto/blob/master/epl-v20
  EDL-V10: https://github.com/eclipse-mosquitto/mosquitto/blob/master/edl-v10

```Eclipse Distribution License - v 1.0

Copyright (c) 2007, Eclipse Foundation, Inc. and its licensors.

All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

  Redistributions of source code must retain the above copyright notice, this
  list of conditions and the following disclaimer.

  Redistributions in binary form must reproduce the above copyright notice,
  this list of conditions and the following disclaimer in the documentation
  and/or other materials provided with the distribution.

  Neither the name of the Eclipse Foundation, Inc. nor the names of its
  contributors may be used to endorse or promote products derived from this
  software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR
ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
(INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON
ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
(INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
```

## Images / Backgrounds
- **Background-Image WebUI**
  Photo by Niklas Jeromin
  Source: [https://www.pexels.com/photo/black-and-white-photo-of-mountains-in-the-snow-19394170/](https://www.pexels.com/photo/black-and-white-photo-of-mountains-in-the-snow-19394170/)

## Notes
- Each software package retains its original license, and you are responsible for ensuring compliance when redistributing or modifying this software.
- Some licenses require attribution, while others impose restrictions on linking with proprietary software.
- If any of these dependencies are redistributed, their corresponding licenses must be included.

For more details, refer to the individual package documentation and licensing terms available from their respective sources.


