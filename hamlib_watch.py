"""Optional read-only rigctld frequency check. Never sends PTT or tune commands."""
import socket


def read_frequency(host='127.0.0.1', port=4532, timeout=1.5):
    host = (host or '127.0.0.1').strip()
    if not host:
        raise ValueError('Hamlib host is empty')
    with socket.create_connection((host, int(port)), timeout=timeout) as connection:
        connection.sendall(b'f\n')
        reply = connection.makefile('rb').readline(64)
    text = reply.decode('ascii', errors='replace').strip()
    if not text or not text.split()[0].isdigit():
        raise RuntimeError('Hamlib did not return a frequency: ' + text)
    return int(text.split()[0])


def compare(expected_hz, host='127.0.0.1', port=4532, slop=200):
    actual = read_frequency(host, port)
    delta = abs(actual - int(expected_hz))
    return {
        'actual': actual,
        'expected': int(expected_hz),
        'ok': delta <= slop,
        'delta': delta,
    }
