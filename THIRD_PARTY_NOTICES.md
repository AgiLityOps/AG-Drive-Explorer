# Third-party notices

The source code in this repository is MIT-licensed (see `LICENSE`), except for the components below, which keep their own licences.

| Component | Where | Licence |
|---|---|---|
| three.js r170 (core build, GLTFLoader, BufferGeometryUtils, meshopt decoder) | `viewer_template/vendor/three/` | MIT, see `viewer_template/vendor/three/LICENSE` |
| meshoptimizer / gltfpack 1.3 | downloaded at build time, shipped inside the release exe | MIT, see `third_party/meshoptimizer_LICENSE.md` |

The release executable also bundles these Python components:

| Component | Licence |
|---|---|
| CPython 3.12 | PSF License |
| PyInstaller bootloader | GPL-2.0 with the bootloader exception |
| numpy | BSD-3-Clause |
| Pillow (with libwebp, libjpeg, zlib) | MIT-CMU (HPND), plus the BSD-style licences of its libraries |
| python-lz4 / LZ4 | BSD-3-Clause / BSD-2-Clause |
| texture2ddecoder | MIT |
| Tcl/Tk (tkinter) | Tcl/Tk License (BSD-style) |
| tkinterdnd2 / tkdnd (optional, drag-and-drop) | MIT / BSD |

No AG Drive game files, game code or values taken from the game are part of this repository or the release executable.
