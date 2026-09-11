# 0.4.0 review closure

This document maps the hostile 0.3.2 review findings to the 0.4.0 implementation. It is evidence for reviewers, not a claim that every RF environment has been exercised.

| Finding | Resolution | Verification |
| --- | --- | --- |
| F01 native validation export | Rebuilt `ghostnet_js8.dll` from the existing DSP source plus the C ABI adapter; startup requires both decode and validation exports. | Export probe and recorded JS8 decode. |
| F02 WAL checkpoint lock | Removed checkpoint execution from inside event transactions; SQLite automatic WAL checkpointing remains enabled. | 250-event regression. |
| F03 clock hunt | Decode grids wait until every ±3 s candidate exists; a quiet locked offset reopens the hunt. UI calls this alignment, not proven PC-clock error. | Recorded fixture decodes at 0 s and +3 s receipt skew. |
| F04 monitor routing/lifecycle | Explicit output is mandatory; volume is bounded; queue/stream/thread are stopped and cleared on failures and Stop. Desktop alerts are silent. | Lifecycle probe and monitor unit test. |
| F05/F06 reports | Plans serialize to primitives; atomic replacement; message-ID session bounds; complete conversations determine `heard`; lane source filters preserve regional accounting. | Report JSON tests and historical-row probe. |
| F07 Tk polling | Poll reschedules after display errors; stored validated settings drive alerts; GUI tests run in isolated processes; self-test cannot overlap reception. | GUI subprocess tests and invalid quiet-hour probe. |
| F08 clipped preferences | Preferences scroll and the installer picker remains fixed above the scroll area. | 850×600 and 1100×760 layout probe. |
| F09 resampling drift | A stateful rational FIR converter preserves exact long-run sample counts across callback boundaries. | 44.1/48 kHz packet-count regression. |
| F10 RTTY polarity/timing | USB mark is 2295 Hz, space 2125 Hz; fractional bit centers and reverse option are supported. Default remains off. | Chunked letters/figures synthetic regression; on-air calibration still required. |
| F11 log lifecycle | Handlers live across receiver failover and close only at session exit; regional lanes use separate rotating files. | Failover log probe. |
| F12 stale audio | Kiwi/Soapy retunes and capture/SDR overflows signal discontinuity, clear decoder state, and discard settling audio. | State-reset tests and code-path inspection. |
| F13 updater identity | Exact setup description/original filename required; version syntax is strict; hash is checked again before launch. | Main application EXE rejection probe. |
| F14 legacy paths | Removed `session.py`, `decoder.py`, `legacy_app.py`, `verify_audio.py`, and the obsolete `KiwiReceiver` CAT controller from the release tree. | Receive-only source scan. |
| F15 coverage/readback | Directory selection filters the currently requested band; USB audio stores frequency as unknown until operator or read-only Hamlib confirmation. | Directory coverage and active-session tests. |

The user reports successful live GhostNet message reception with an earlier build. The 0.4.0 changes were independently checked with the bundled recording. Live SoapySDR hardware and on-air RTTY calibration remain unverified.
