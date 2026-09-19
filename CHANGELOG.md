# Changelog

## Unreleased

- Fixed CAT sideband display, duplicate polling after an installer launch failure, and RTTY recordings spanning audio gaps or separate windows.

- Added a net-night guide with direct report/export/archive actions.
- Added a dedicated read-only radio-frequency status line instead of appending CAT state to the tune banner.
- Added monitor-only automatic level control; the decoder continues to receive the untouched 12 kHz stream.
- Added an adjustable RTTY audio center and optional raw calibration WAV while retaining the published 170 Hz shift and preview status.
- Added isolated normal-close coverage for Tk's owned polling timer.

## 0.4.0

- Added concurrent North America, Europe, and Australia/Pacific KiwiSDR lanes with separate live tabs and a combined searchable archive.
- Rebuilt the receive-only native DLL so startup and multi-frame assembly have the required checksum-validation export. The upstream JS8 DSP portion is unchanged.
- Fixed JS8 UTC-window hunting for capture/network offsets through ±3 seconds, including recovery after quiet periods.
- Added continuous packet-boundary-safe 44.1/48 kHz conversion, explicit discontinuity handling, and retune settling.
- Corrected the 45.45 baud RTTY USB polarity and fractional symbol timing. RTTY remains an opt-in preview pending on-air calibration.
- Made session reports atomic, session-bounded, and based on completed conversations. Regional sessions write separate reports and rotating logs.
- Made Hear audio require an explicit playback endpoint, added volume, and reliably stopped/cleared its worker on every exit path.
- Added an operator frequency-confirmation action for USB-audio radios and retained read-only Hamlib frequency checks.
- Removed legacy UDP/CAT entry points and their obsolete tests. SoapySDR remains optional and is excluded from packaged builds.
- Hardened local installer inspection and rechecks the selected file hash immediately before launch.

## 0.3.2

- Initial integrated GUI, KiwiSDR and USB-audio receive paths, scheduler, journal, reports, alerts, and unsigned installer work.
