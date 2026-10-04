# Changelog

## 0.4.2

- Fix split JS8 callsign/destination/body assembly so message bodies inherit GhostNet tags. Missing callsign headers remain incomplete; ambiguous overlapping traffic stays separate.
- Display traffic oldest-to-newest, preserve the selected message as it grows, enlarge the reading pane, and make raw frames optional.
- Include the previous locally developed 0.4.1 regional audio, receiver cache, decoder locking, and display updates.
- Receive-only unsigned Windows Setup and portable package. Existing journal entries are preserved; these assembly fixes apply to new reception.

## 0.4.1

- Local development build: unsigned Setup includes net-night guide, CAT line, RTTY calibration, and per-lane Hear audio.
- All-region monitoring now saves tagged JS8 WAVs. Hear one region at a time from Regional feeds.
- Shared Kiwi directory cache so three lanes do not fetch the listing three times.
- Decode stays process-safe across lanes (DLL static decoder). Hunt uses Normal-only until locked to cut CPU.
- Start reminds you to sync Windows time before 0100z.
- Watch-floor GUI: phosphor green / amber on black, UTC clock, RECEIVE ONLY masthead.

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

## Local reception fixes

- Join compound callsign and directed destination headers before assembling JS8 body frames. Linked raw frames inherit the conversation tag; ambiguous or missing headers stay separate.
- Read inbox and regional feeds oldest-to-newest, preserve the selected message during live updates, enlarge the message pane, and hide individual frames until requested.
