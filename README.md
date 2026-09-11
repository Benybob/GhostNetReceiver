# GhostNet Receiver

**Receive-only Windows listener for published GhostNet JS8 traffic.**

This independent desktop app selects a public KiwiSDR (or your radio’s USB audio), follows the [GhostNet v1.5](https://github.com/s2underground/GhostNet) regional schedule, decodes JS8 **in process**, and stores messages only on this computer. It does **not** transmit, does **not** require JS8Call, and is **not** affiliated with GhostNet or JS8Call.

Current release: **0.4.0** (unsigned Windows Setup).

## What it does

- Listens on the published JS8 windows (North America, Europe, Australia / Pacific).
- Optional **Monitor all regions** runs three independent online receiver lanes at once. Regional tabs and the combined inbox retain the receiver/region provenance for every copy.
- Decodes JS8 inside the program (`ghostnet_js8.dll`, based on JS8Call Improved, receive path only).
- Defaults the inbox to `@GHOSTNET`, `@GSTFLASH`, and `@GN…` tagged traffic. Incomplete multi-frame messages stay marked incomplete.
- Follows the rest of the published hour honestly: VARA and ALE are **not** decoded (the app stays on 40 m JS8); RTTY 45.45 on 7.077 MHz is an **opt-in preview**; voice is a **7.190 MHz LSB tune reminder** only.
- Optional **Hear audio** plays the receive stream on headphones/speakers you choose. That is monitor audio, not PTT.
- Optional USB audio from a transceiver (you tune the radio). Optional SoapySDR USB dongle if you already have PothosSDR installed (not bundled).
- Optional Hamlib is **GET frequency only** (`f`). No tune, no PTT.
- Local SQLite journal under `%LOCALAPPDATA%\GhostNetReceiver\data`. Stop listening writes `data\net-night\report.json`.

## Install (Windows)

1. Download **GhostNetReceiver-0.4.0-Setup.exe** from [Releases](../../releases).
2. Compare SHA-256 with `SHA256SUMS.txt` on the same release.
3. The installer is **not Authenticode-signed**. SmartScreen: **More info → Run anyway**.
4. It installs to `%LOCALAPPDATA%\Programs\GhostNetReceiver` (no administrator required).
5. Choose your region → **Start listening**.

To collect the three published regions concurrently, open **Advanced**, enable **Monitor all published regions at once**, and start listening. This uses three public KiwiSDR connections. A lane that loses audio is clearly marked and fails over independently. Public receiver capacity and HF propagation mean this improves coverage but cannot guarantee every transmission.

Keep the AppData `data` folder when you upgrade. Do not replace it with the program folder.

### Run from source

Python 3.11+ on Windows:

```text
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
Start.cmd
```

`bin\ghostnet_js8.dll` and its Qt/FFTW companions must sit next to the source tree.

## What it does not do

- No transmit, heartbeat TX, spotting, or CAT writes.
- No VARA, ALE, or voice transcription.
- No bundled SoapySDR/PothosSDR.
- No claim that a short off-net listen proves a GhostNet QSO. Use **Net report** after a published window.
- No silent upload or central collection. The regional archive remains on this computer until you export it.

## Schedule (GhostNet v1.5)

Times are UTC. North America weekly is **Friday UTC** (Thursday evening in much of the US).

| Region | Window | Mode in this app |
| --- | --- | --- |
| North America | Fri 0100–0130 7.107 | JS8 decoded |
| | Fri 0130–0200 7.107 VARA | Not decoded; stay on 7.107 JS8 |
| | Fri 0200–0230 7.077 45.45 | RTTY preview if enabled |
| | Fri 0230–0300 7.190 LSB | Tune reminder; online stays on 7.107 JS8 |
| Saturday bridges | 14.107 / 3.575 JS8 | Decoded; yellow **SWITCH BAND** banner |

Europe Thursday 1800z and Australia Thursday 0700z follow the same JS8-first pattern. See the published PDF for the authoritative plan.

## License

Application and native adapter: **GPL-3.0-or-later**. JS8Call Improved, KiwiClient, Qt, FFTW, and other attributions are in [THIRD_PARTY.md](THIRD_PARTY.md).

## Disclaimer

Radio conditions, receiver availability, PC clock error, and an empty band all cause missed traffic. Tags do not authenticate a sender. This project is a listener for a published amateur-radio net, not an official GhostNet product.
