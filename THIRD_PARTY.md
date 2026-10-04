# Source and attribution

GhostNet Receiver 0.4.1. Application and native adapter: GPL-3.0-or-later; see LICENSE. Corresponding application and native sources, build configuration, packaging specification and unsigned Inno Setup script accompany the Windows build.

JS8Call Improved 3.0.3, commit 4c592bd9a034f18178a3e7179db92acb14939668: https://github.com/JS8Call-improved/JS8Call-improved — GPL-3.0-or-later. Selected upstream files and vendored Eigen/CRCpp are under native/upstream. The generated engine omits the GUI worker and exposes synchronous receive callbacks. Numeric encoding math remains for receive signal subtraction. The recorded fixture comes from the original JS8Call media/tests corpus.

KiwiClient, commit 4eb733e6b6147f7fbeb97ced64cdac029b202d18: https://github.com/jks-prv/kiwiclient — source and notices are included under vendor/kiwiclient, including mod_pywebsocket notices.

Native build: GCC 16.1.0, QtCore 6.11.1, FFTW 3.3.11 and Boost 1.91.0. Runtime dependencies include ICU 78, PCRE2, libb2, double-conversion, zlib, zstd and winpthreads. Available distribution license texts are in licenses. Source distributions and build recipes are available at https://github.com/msys2/MINGW-packages and upstream Qt and FFTW download sites. Qt and FFTW are used under GPL-compatible terms. Libraries remain replaceable in _internal/bin.

Python 3.12, Tcl/Tk, NumPy, SciPy, sounddevice, SoundCard and PyInstaller retain their upstream licenses. The build uses requirements.txt and GhostNetReceiver.spec.

Schedule: S2 Underground GhostNet v1.5, https://github.com/s2underground/GhostNet, CC BY-NC-SA 4.0. Schedule adaptation retains this separate attribution and license. This is a noncommercial preview.

Rebuild the native library using MSYS2 MinGW64 GCC, CMake, Ninja, Qt6-base, Boost and FFTW. Put MinGW64/bin on PATH, run `cmake -S native -B build -G Ninja -DCMAKE_BUILD_TYPE=Release`, then `cmake --build build`. Copy the resulting DLL and runtime dependencies to bin. Selected sources and generated engine are supplied; extraction is not necessary. To rebuild the portable app, install requirements.txt and PyInstaller, then run `python -m PyInstaller GhostNetReceiver.spec`.
