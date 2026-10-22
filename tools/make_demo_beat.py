"""Create an original 8-bar, 90 BPM drum/bass loop using only Python's stdlib."""
import argparse
import math
import random
import struct
import wave
from pathlib import Path


def make_beat(destination):
    rate, bpm, bars = 24000, 90, 8
    step = 60 / bpm
    samples = [0.0] * int(rate * step * 4 * bars)
    rng = random.Random(101)
    for beat in range(bars * 4):
        start = int(beat * step * rate)
        for i in range(int(rate * 0.35)):
            t = i / rate
            samples[start + i] += 0.36 * math.sin(2 * math.pi * (48 * t + 1.8 * (1 - math.exp(-35 * t)))) * math.exp(-16 * t)
            if beat % 2:
                samples[start + i] += 0.16 * rng.uniform(-1, 1) * math.exp(-27 * t)
        bass = (65.41, 65.41, 77.78, 58.27)[(beat // 4) % 4]
        for i in range(int(rate * step * 0.85)):
            t = i / rate
            samples[start + i] += 0.15 * math.sin(2 * math.pi * bass * t) * min(1, t * 80) * math.exp(-4 * t)
        for half in (0, 1):
            hat_start = start + int(half * step * rate / 2)
            for i in range(int(rate * 0.06)):
                samples[hat_start + i] += 0.07 * rng.uniform(-1, 1) * math.exp(-75 * i / rate)
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive create protects any beat the user already placed here.
    with destination.open("xb") as output, wave.open(output, "wb") as wav:
        wav.setparams((1, 2, rate, 0, "NONE", "not compressed"))
        wav.writeframes(b"".join(struct.pack("<h", int(max(-1, min(1, s)) * 30000)) for s in samples))
    return destination


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parent.parent / "beats" / "sloth-hop.wav")
    args = parser.parse_args()
    try:
        print(f"Created {make_beat(args.output)}")
    except FileExistsError:
        parser.exit(1, f"Beat already exists: {args.output}\n")
