# Validation — 0.4.2

Source suite: 53 tests, including split compound headers, inherited body tags, incomplete missing headers, ambiguous overlaps, chronological GUI order and selection, recorded JS8, and update/audio lifecycle regressions.

Packaged decoder and isolated installer validation are recorded with the release notes. No new live RF or on-air RTTY validation is claimed. Existing messages are retained; old conversations are not automatically reassembled.

# Validation — 0.4.1

Tonight's unsigned installer. Per-lane Hear audio, fleet net-night WAV capture, shared Kiwi directory cache, process-wide decode lock, Normal-only hunt until locked.

# Validation — 0.4.0

The 0.3.2 hostile review findings are addressed in this tree; see `REVIEW_FIXES.md` for the mapping.

- `ghostnet_validate_message` is exported by `bin/ghostnet_js8.dll` (copied from `work/native-build`). Startup refuses a DLL missing that export.
- Journal events no longer `wal_checkpoint` inside the write transaction. 250 sequential events commit.
- Clock hunt waits until the +3 s window exists before consuming a quiet UTC grid; it does not lock to “band is quiet” forever.
- Session reports serialize `Window`/`datetime`, count only this session’s complete tagged conversations, and write atomically.
- Hear audio requires an Advanced speaker/headphone choice; Stop joins the monitor worker.
- Preferences tab scrolls. Invalid quiet-hour text no longer kills Tk polling.
- Receiver discovery filters the scheduled frequency (including 14.107 / 3.575 bridges).
- `inspect_installer` rejects the application EXE. Spec excludes `SoapySDR`. `legacy_app.py` is not an entry point.

42 automated tests pass, including native checksum export, packet-safe resampling, regional fleet construction, 250 event writes, report JSON, chunked RTTY, recorded JS8, and isolated Tk GUI smoke tests.

The recorded 95-second alignment regression produced 12 JS8 frames at nominal receipt time and 10 frames with a +3 second receipt skew. The launch checks cover `python app.py`, `Start.cmd`, and the frozen application self-test.

The unsigned Setup executable completed a silent per-user installation into an isolated test directory; the installed executable then passed the four-frame frozen self-test. A pre-existing data sentinel outside the program directory remained intact.

User field testing received GhostNet messages with an earlier build. Live SoapySDR hardware and on-air RTTY remain unverified.

# Historical validation — 0.3.2

## Product

- Inbox defaults to GhostNet-tagged conversations; incomplete states stay visible; FLASH alerts default on and override quiet hours.
- Schedule follow: JS8 decoded; VARA holds 7.107 JS8; RTTY 45.45 preview on 7.077; voice banner 7.190 LSB without transcription; Saturday data bridges prompt SWITCH BAND.
- USB audio meter, remembered device, large tune banner. Hamlib check is GET frequency only.
- Session log rotates at 1 MB × 5. SQLite WAL checkpoints. Event table is pruned past 20k rows.
- Stop listening writes `data/net-night/report.json`. Tagged JS8 can save a 15 s WAV.
- Installer SHA-256 is written to `SHA256SUMS.txt`. Setup remains unsigned.

## Tests

Automated tests cover listen_plan windows, RTTY round-trip of `GHOSTNET`, GhostNet CSV export, heard report, Hamlib read-only parse, native JS8 pipeline, and GUI smoke.

## Still unverified

A real Thursday-night GhostNet net on 7.107 MHz. Live USB transceiver. Live SoapySDR dongle. RTTY on the air (synthetic only).
