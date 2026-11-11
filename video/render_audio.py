#!/usr/bin/env python3
"""Render the Hyperframes score from audio/cues.json (stdlib only).

Deterministic: the same cue sheet produces a byte-identical WAV. The preview
and the MP4 both consume this file, so the page never schedules cues itself.
"""
from __future__ import annotations

import argparse
import array
import json
import math
import random
import struct
import wave
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_CUES = HERE / "audio" / "cues.json"
DEFAULT_OUT = HERE / "audio" / "mix.wav"
TWO_PI = 2 * math.pi
MASTER_PEAK = 0.89  # -1 dBFS


def db(x: float) -> float:
    return 10 ** (x / 20)


def noise(n: int, rng: random.Random) -> list[float]:
    return [rng.uniform(-1.0, 1.0) for _ in range(n)]


def one_pole_lp(samples: list[float], cutoff: float, sr: int) -> list[float]:
    a = 1 - math.exp(-TWO_PI * cutoff / sr)
    out = [0.0] * len(samples)
    y = 0.0
    for i, x in enumerate(samples):
        y += a * (x - y)
        out[i] = y
    return out


def tone(freq: float, dur: float, tau: float, sr: int) -> list[float]:
    n = int(round(dur * sr))
    return [
        math.sin(TWO_PI * freq * i / sr) * math.exp(-(i / sr) / tau)
        for i in range(n)
    ]


def make_click(sr: int, rng: random.Random) -> list[float]:
    n = int(round(0.010 * sr))
    out = [0.0] * n
    for i, v in enumerate(noise(int(round(0.006 * sr)), rng)):
        out[i] += v
    for i in range(n):
        t = i / sr
        out[i] += 0.7 * math.sin(TWO_PI * 2000 * t) * math.exp(-t / 0.002)
    return out


def make_tick(sr: int, _rng: random.Random) -> list[float]:
    return tone(1600, 0.012, 0.005, sr)


def make_sweep(sr: int, _rng: random.Random) -> list[float]:
    dur = 0.180
    n = int(round(dur * sr))
    f0, f1 = 400.0, 1400.0
    out = [0.0] * n
    for i in range(n):
        t = i / sr
        phase = TWO_PI * (f0 * t + (f1 - f0) * t * t / (2 * dur))
        out[i] = math.sin(phase) * math.sin(math.pi * t / dur)
    return out


def make_whoosh(sr: int, rng: random.Random) -> list[float]:
    n = int(round(0.320 * sr))
    raw = noise(n, rng)
    hi = one_pole_lp(raw, 2500, sr)
    lo = one_pole_lp(raw, 400, sr)
    return [
        (hi[i] - lo[i]) * math.sin(math.pi * i / (n - 1)) ** 2 for i in range(n)
    ]


def make_bell(sr: int, _rng: random.Random) -> list[float]:
    a = tone(1760, 0.6, 0.180, sr)
    b = tone(2640, 0.6, 0.180, sr)
    return [x + 0.7 * y for x, y in zip(a, b)]


def make_thud(sr: int, rng: random.Random) -> list[float]:
    body = tone(65, 0.220, 0.070, sr)
    n = int(round(0.020 * sr))
    for i, v in enumerate(noise(n, rng)):
        body[i] += 0.5 * v
    return body


def make_blip(sr: int, _rng: random.Random) -> list[float]:
    return tone(990, 0.090, 0.030, sr)


def make_chime(sr: int, _rng: random.Random) -> list[float]:
    n = int(round(0.960 * sr))
    out = [0.0] * n
    low = tone(880, 0.900, 0.300, sr)
    high = tone(1320, 0.840, 0.300, sr)
    offset = int(round(0.060 * sr))
    for i, v in enumerate(low):
        out[i] += v
    for i, v in enumerate(high):
        out[offset + i] += 0.7 * v
    return out


def make_boom(sr: int, rng: random.Random) -> list[float]:
    body = tone(45, 0.350, 0.120, sr)
    for i, v in enumerate(make_click(sr, rng)):
        body[i] += 0.8 * v
    return body


SAMPLES = {
    "click": make_click,
    "tick": make_tick,
    "sweep": make_sweep,
    "whoosh": make_whoosh,
    "bell": make_bell,
    "thud": make_thud,
    "blip": make_blip,
    "chime": make_chime,
    "boom": make_boom,
}


def expand(events: list[dict], duration_ms: int) -> list[tuple[float, str, float]]:
    out: list[tuple[float, str, float]] = []
    for event in events:
        if "typing" in event:
            t = event["typing"]
            n = math.ceil(t["chars"] / t["every"])
            for i in range(n):
                at = t["fromMs"] + (i * (t["toMs"] - t["fromMs"]) / (n - 1) if n > 1 else 0)
                out.append((at, t["sample"], t["db"]))
        else:
            out.append((event["atMs"], event["sample"], event["db"]))
    return out


def place(
    left: list[float],
    right: list[float],
    sr: int,
    at_ms: float,
    samples: list[float],
    gain_db: float,
    gl: float = 1.0,
    gr: float = 1.0,
) -> None:
    start = int(round(at_ms * sr / 1000))
    if start < 0:
        samples = samples[-start:]
        start = 0
    if start >= len(left) or not samples:
        return
    peak = max(abs(v) for v in samples)
    if peak == 0:
        return
    k = db(gain_db) / peak
    for i, v in enumerate(samples):
        j = start + i
        if j >= len(left):
            break
        left[j] += v * k * gl
        right[j] += v * k * gr


def render_bed(
    sr: int,
    n: int,
    cfg: dict,
    duck_spans: list[dict],
    rng: random.Random,
) -> tuple[list[float], list[float]]:
    left = [0.0] * n
    right = [0.0] * n
    trem = [1 + 0.1 * math.sin(TWO_PI * 0.08 * i / sr) for i in range(n)]
    attack = int(round(1.2 * sr))
    release = int(round(0.6 * sr))
    env = [
        min(1.0, i / attack) * min(1.0, (n - 1 - i) / release) for i in range(n)
    ]

    # Pad: each note twice, detuned, opposite pans.
    for freq in cfg["notes"]:
        for det, gl, gr in ((-0.0012, 0.35, 0.65), (0.0012, 0.65, 0.35)):
            f = freq * (1 + det)
            g = db(-36)
            for i in range(n):
                v = g * math.sin(TWO_PI * f * i / sr) * trem[i] * env[i]
                left[i] += v * gl
                right[i] += v * gr

    # Sub drone.
    g = db(-26)
    for i in range(n):
        v = g * math.sin(TWO_PI * 55 * i / sr)
        left[i] += v
        right[i] += v

    # 120 BPM pulse (60 Hz), skipped under the duck span.
    pulse = tone(60, 0.140, 0.045, sr)
    pulse_peak = max(abs(v) for v in pulse)
    pulse = [v / pulse_peak * db(-20) for v in pulse]
    beat_ms = int(round(60000 / cfg["bpm"]))
    for at_ms in range(0, int(round(n / sr * 1000)), beat_ms):
        if any(s["fromMs"] <= at_ms < s["toMs"] for s in duck_spans):
            continue
        start = int(round(at_ms * sr / 1000))
        for i, v in enumerate(pulse):
            j = start + i
            if j >= n:
                break
            left[j] += v
            right[j] += v

    # Hats on eighths, alternating channels.
    hat_len = int(round(0.018 * sr))
    for k, at_ms in enumerate(range(0, int(round(n / sr * 1000)), 250)):
        raw = noise(hat_len, rng)
        lp = one_pole_lp(raw, 6000, sr)
        hat = [raw[i] - lp[i] for i in range(hat_len)]
        peak = max(abs(v) for v in hat)
        if peak == 0:
            continue
        gain = db(-36 if k % 2 == 0 else -38) / peak
        gl, gr = (0.7, 0.3) if k % 2 == 0 else (0.3, 0.7)
        start = int(round(at_ms * sr / 1000))
        for i, v in enumerate(hat):
            j = start + i
            if j >= n:
                break
            left[j] += v * gain * gl
            right[j] += v * gain * gr

    # Duck the whole bed under the rename beat.
    for span in duck_spans:
        a = int(round(span["fromMs"] * sr / 1000))
        b = min(n, int(round(span["toMs"] * sr / 1000)))
        ramp = max(1, int(round(0.120 * sr)))
        target = db(span["db"])
        for i in range(a, b):
            if i < a + ramp:
                k = 1 + (target - 1) * (i - a) / ramp
            elif i >= b - ramp:
                k = target + (1 - target) * (i - (b - ramp)) / ramp
            else:
                k = target
            left[i] *= k
            right[i] *= k

    return left, right


def write_wav(path: Path, sr: int, left: list[float], right: list[float]) -> None:
    n = min(len(left), len(right))
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(sr)
        for start in range(0, n, 4096):
            chunk = []
            for i in range(start, min(n, start + 4096)):
                chunk.append(max(-32768, min(32767, round(left[i] * 32767))))
                chunk.append(max(-32768, min(32767, round(right[i] * 32767))))
            w.writeframes(struct.pack("<%dh" % len(chunk), *chunk))


def load_cues(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def render(cues_path: Path, out_path: Path) -> None:
    cfg = load_cues(cues_path)
    sr = int(cfg["sampleRate"])
    if int(cfg["channels"]) != 2:
        raise SystemExit("cues.json: only stereo output is supported")
    n = int(round(cfg["durationMs"] * sr / 1000))
    rng = random.Random(0)
    duck_spans = cfg["bed"].get("duck", [])
    left, right = render_bed(sr, n, cfg["bed"], duck_spans, rng)

    cache = {name: fn(sr, rng) for name, fn in SAMPLES.items()}
    for at_ms, name, gain_db in expand(cfg["events"], cfg["durationMs"]):
        place(left, right, sr, at_ms, cache[name], gain_db)

    peak = max(max(abs(v) for v in left), max(abs(v) for v in right))
    if peak > 0:
        k = MASTER_PEAK / peak
        left = [v * k for v in left]
        right = [v * k for v in right]
    write_wav(out_path, sr, left, right)


def check(cues_path: Path, out_path: Path) -> None:
    cfg = load_cues(cues_path)
    sr = int(cfg["sampleRate"])
    duration_ms = float(cfg["durationMs"])
    events = expand(cfg["events"], duration_ms)
    for at_ms, name, _gain in events:
        if name not in SAMPLES:
            raise SystemExit(f"cues.json: unknown sample {name!r}")
        if not 0 <= at_ms < duration_ms:
            raise SystemExit(f"cues.json: event {name} at {at_ms}ms is out of range")
    with wave.open(str(out_path), "rb") as w:
        frames = w.getnframes()
        rate = w.getframerate()
        channels = w.getnchannels()
        raw = w.readframes(frames)
    expected = int(round(duration_ms * sr / 1000))
    if rate != sr or channels != 2 or frames != expected:
        raise SystemExit(
            f"mix.wav: expected {expected} frames at {sr}Hz stereo, "
            f"got {frames} frames at {rate}Hz x{channels}"
        )
    data = array.array("h")
    data.frombytes(raw)
    peak = max(max(data), -min(data)) / 32767
    peak_db = 20 * math.log10(peak) if peak else float("-inf")
    if peak_db > -0.5:
        raise SystemExit(f"mix.wav: peak {peak_db:.2f}dBFS is too hot")
    print(
        f"OK duration={duration_ms / 1000:.2f}s events={len(events)} "
        f"peak={peak_db:.2f}dBFS sr={rate} ch={channels}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cues", type=Path, default=DEFAULT_CUES)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        check(args.cues, args.out)
    else:
        render(args.cues, args.out)
        check(args.cues, args.out)


if __name__ == "__main__":
    main()
