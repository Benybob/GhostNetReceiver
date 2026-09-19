"""Receive-only 45.45 baud ITA2 RTTY from 12 kHz mono audio. Preview quality."""
import numpy as np

BAUD = 45.45
# Published 170 Hz shift on USB: mark is the higher audio tone.
MARK_HZ = 2295.0
SPACE_HZ = 2125.0
RATE = 12000
SAMPLES_PER_BIT = RATE / BAUD
LETTERS = {
    0x03: 'A', 0x19: 'B', 0x0E: 'C', 0x09: 'D', 0x01: 'E', 0x0D: 'F', 0x1A: 'G',
    0x14: 'H', 0x06: 'I', 0x0B: 'J', 0x0F: 'K', 0x12: 'L', 0x1C: 'M', 0x0C: 'N',
    0x18: 'O', 0x16: 'P', 0x17: 'Q', 0x0A: 'R', 0x05: 'S', 0x10: 'T', 0x07: 'U',
    0x1E: 'V', 0x13: 'W', 0x1D: 'X', 0x15: 'Y', 0x11: 'Z',
    0x04: ' ', 0x08: '\r', 0x02: '\n', 0x1F: '\x0e', 0x1B: '\x0f', 0x00: '',
}
FIGURES = {
    0x03: '-', 0x19: '?', 0x0E: ':', 0x09: '$', 0x01: '3', 0x0D: '!', 0x1A: '&',
    0x14: '#', 0x06: '8', 0x0B: "'", 0x0F: '(', 0x12: ')', 0x1C: '.', 0x0C: ',',
    0x18: '9', 0x16: '0', 0x17: '1', 0x0A: '4', 0x05: '\a', 0x10: '5', 0x07: '7',
    0x1E: ';', 0x13: '2', 0x1D: '/', 0x15: '6', 0x11: '"',
    0x04: ' ', 0x08: '\r', 0x02: '\n', 0x1F: '\x0e', 0x1B: '\x0f', 0x00: '',
}


def goertzel(chunk, hz, rate=RATE):
    n = len(chunk)
    if n < 8:
        return 0.0
    k = int(0.5 + (n * hz) / rate)
    w = 2 * np.pi * k / n
    coeff = 2 * np.cos(w)
    s0 = s1 = s2 = 0.0
    for sample in chunk:
        s0 = sample + coeff * s1 - s2
        s2, s1 = s1, s0
    return s1 * s1 + s2 * s2 - coeff * s1 * s2


def encode_bits(text):
    """Test helper: ITA2 bits including start (0) and two stop (1) bits, letters case."""
    inverse = {letter: code for code, letter in LETTERS.items() if letter and letter not in '\x0e\x0f'}
    bits = []
    figs = False
    for char in text.upper():
        if char.isdigit() or char in '-,:$?!&.\'()#./;"':
            if not figs:
                bits.extend(_frame(0x1B)); figs = True
            bits.extend(_frame(next(code for code, glyph in FIGURES.items() if glyph == char)))
        else:
            if figs and char.isalpha():
                bits.extend(_frame(0x1F)); figs = False
            bits.extend(_frame(inverse.get(char, 0x04)))
    return bits


def _frame(code):
    return [0] + [(code >> bit) & 1 for bit in range(5)] + [1, 1]


def synthesize(text, seconds=None):
    bits = encode_bits(text)
    total = int(len(bits) * SAMPLES_PER_BIT)
    t = np.arange(total) / RATE
    wave = np.zeros(total, dtype=np.float64)
    for index, bit in enumerate(bits):
        start = int(index * SAMPLES_PER_BIT)
        end = int((index + 1) * SAMPLES_PER_BIT)
        hz = MARK_HZ if bit else SPACE_HZ
        wave[start:end] = np.sin(2 * np.pi * hz * t[start:end])
    samples = np.clip(np.rint(wave * 16000), -32768, 32767).astype(np.int16)
    if seconds:
        need = int(seconds * RATE)
        if len(samples) < need:
            samples = np.concatenate([samples, np.zeros(need - len(samples), dtype=np.int16)])
    return samples


class RttyDecoder:
    def __init__(self, reverse=False, center_hz=2210.0):
        self.reverse = bool(reverse)
        self.center_hz = float(center_hz)
        if not 500 <= self.center_hz <= 3500:
            raise ValueError('RTTY audio center must be 500 through 3500 Hz')
        self.buffer = np.empty(0, dtype=np.int16)
        self.figures = False
        self.pending = ''

    def feed(self, samples):
        data = np.ascontiguousarray(samples, dtype=np.int16)
        self.buffer = np.concatenate([self.buffer, data])
        keep = int(SAMPLES_PER_BIT * 40)
        if len(self.buffer) > keep * 4:
            self.buffer = self.buffer[-keep * 3:]
        emitted = []
        while True:
            char = self._next_char()
            if char is None:
                break
            if char == '\x0e' or char == '':
                continue
            if char == '\x0f':
                self.figures = True
                continue
            if char == '\x0e':
                self.figures = False
                continue
            self.pending += char
            if char in '\r\n' and len(self.pending.strip()) >= 2:
                emitted.append(self.pending.replace('\r', '').replace('\n', ' ').strip())
                self.pending = ''
            elif len(self.pending) >= 80:
                emitted.append(self.pending.strip())
                self.pending = ''
        return emitted

    def _next_char(self):
        width = SAMPLES_PER_BIT
        required = int(np.ceil(width * 7.5))
        if len(self.buffer) < required:
            return None
        # Hunt a space start bit, then sample each bit at its center. Floating-point
        # centers avoid the cumulative timing drift caused by rounding 264.026 samples.
        limit = len(self.buffer) - required
        half = max(20, int(width * .16))
        for origin in range(0, max(1, limit + 1), 2):
            if origin and not self._tone(origin - .20 * width, half):
                continue
            if self._tone(origin + .25 * width, half) or self._tone(origin + .75 * width, half):
                continue
            bits = 0
            for bit in range(5):
                if self._tone(origin + (bit + 1.5) * width, half):
                    bits |= 1 << bit
            if not self._tone(origin + 6.3 * width, half) or not self._tone(origin + 6.8 * width, half):
                continue
            self.buffer = self.buffer[int(round(origin + 7.25 * width)):]
            table = FIGURES if self.figures else LETTERS
            glyph = table.get(bits, '')
            if bits == 0x1B:
                self.figures = True
                return ''
            if bits == 0x1F:
                self.figures = False
                return ''
            return glyph
        # Retain enough tail to recognize a start bit split across callbacks.
        discard=max(1,len(self.buffer)-required+1)
        self.buffer = self.buffer[discard:]
        return None

    def _tone(self, center, half):
        center=int(round(center))
        return self._mark(self.buffer[max(0,center-half):center+half])

    def _mark(self, chunk):
        audio = chunk.astype(np.float64)
        mark = goertzel(audio, self.center_hz + 85) >= goertzel(audio, self.center_hz - 85)
        return (not mark) if self.reverse else mark
