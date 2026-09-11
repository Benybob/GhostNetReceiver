# Contributing

This project is a **receive-only** amateur-radio listener.

Please do **not** send pull requests that add transmit, PTT, CAT writes, spotting, VARA, ALE, or voice ASR.

Useful contributions: live net-night logs, RTTY calibration recordings, installer/signing notes, tests that do not require RF transmit.

Run tests:

```text
.\.venv\Scripts\python.exe -m unittest test_native.py test_receiver.py
```
