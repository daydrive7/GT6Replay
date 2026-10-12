# Third-party software

Application code is covered by `LICENSE`. Dependency notices are in `LICENSES`, with additional Python, Qt, and PDTools notices at the repository root. Retain these notices when redistributing a build.

| Component | Version | License / source |
| --- | --- | --- |
| Python | 3.13 | PSF; `Python-LICENSE.txt`; [source](https://www.python.org/downloads/source/) |
| NumPy | 2.4.4 | BSD and included numerical-library notices; `LICENSES/numpy`; [source](https://github.com/numpy/numpy/tree/v2.4.4) |
| cryptography | 48.0.1 | Apache-2.0 or BSD-3-Clause; `LICENSES/cryptography`; [source](https://github.com/pyca/cryptography/tree/48.0.1) |
| CFFI / pycparser | 2.0.0 / 3.0 | BSD notices in `LICENSES/cffi`, `LICENSES/pycparser` |
| OpenSSL | Versions used by Python and cryptography | Apache-2.0; matching notices in `LICENSES/OpenSSL`; [source](https://github.com/openssl/openssl) |
| PySide6 / Shiboken6 | 6.11.0 | LGPLv3 option; `LICENSES/PySide6*`, `LICENSES/shiboken6` |
| Qt Base, SVG, Image Formats | 6.11.0 | LGPLv3 and included third-party notices; `Qt-LGPL-3.0-only.txt`, `LICENSES/Qt-Sources` |
| PyInstaller | 6.22.3 | GPL with bootloader exception; `LICENSES/pyinstaller`; [source](https://github.com/pyinstaller/pyinstaller/tree/v6.22.3) |
| PDTools format/protocol references | — | Nenkai, MIT; `PDTools-MIT.txt`; [source](https://github.com/Nenkai/PDTools) |

Qt Virtual Keyboard, PDF, QML, and Quick plugins/libraries are excluded from this widget-based Windows package. The build audit rejects them.

## Qt corresponding source

The Windows release is accompanied by the unmodified Qt 6.11.0 and PySide6 6.11.0 source archives, listed with hashes in `third-party-sources.json`. They may also be obtained from these official locations:

- [Qt 6.11.0 module sources](https://download.qt.io/official_releases/qt/6.11/6.11.0/submodules/): `qtbase-everywhere-src-6.11.0.tar.xz`, `qtsvg-everywhere-src-6.11.0.tar.xz`, `qtimageformats-everywhere-src-6.11.0.tar.xz`.
- [PySide6 / Shiboken6 6.11.0 sources](https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.11.0-src/).
- [Qt build instructions](https://doc.qt.io/qt-6/build-sources.html), [PySide build instructions](https://doc.qt.io/qtforpython-6.11/building_from_source/index.html).

Qt and PySide libraries are dynamically loaded from `_internal/PySide6` and `_internal/shiboken6`. Users may replace them with ABI-compatible modified builds, or run the application from its MIT-licensed Python source with a replacement PySide installation. No signature or installation lock prevents replacement. Reverse engineering to debug modifications to these libraries is permitted under their licenses.

The source archives must accompany binary publication; `scripts/fetch_sources.py` obtains them and preserves source license notices. The release workflow attaches them alongside the Windows ZIP.
