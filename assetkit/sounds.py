#!/usr/bin/env python3
"""Short game sound effects, synthesized with numpy. Mono, under 2 seconds, written as .ogg with ffmpeg.

    from assetkit import sounds
    sounds.save(sounds.block_break("stone", seed=1), "break.ogg")
    sounds.mob_set("out/sounds", "ember_husk", voice="grunt", seed=3)

Command line:  python3 assetkit/sounds.py block_hit --material wood --seed 2 -o hit.ogg
               python3 assetkit/sounds.py list

Minecraft only plays Ogg Vorbis. If ffmpeg is missing, save() writes a .wav beside the requested path and
warns on stderr: that file is fine for checking but the game can't play it.
"""
import argparse
import inspect
import pathlib
import shutil
import subprocess
import sys
import wave

import numpy as np

RATE = 44100
MAX_SECONDS = 2.0
MATERIALS = ("stone", "wood", "metal", "soil", "glass", "plant")
VOICES = {  # base pitch in Hz, roughness, formants in Hz, noise share
    "grunt": (92, 0.45, (420, 1000, 2400), 0.10),
    "growl": (68, 0.80, (340, 860, 2100), 0.18),
    "squeak": (620, 0.10, (1300, 2600, 4200), 0.04),
    "hollow": (118, 0.12, (300, 780, 1700), 0.06),
    "gloop": (150, 0.20, (520, 1200, 2000), 0.03),
    "hiss": (180, 0.35, (1800, 3400, 5600), 0.70),
}


# ---------------------------------------------------------------- building blocks

def _n(seconds):
    return int(round(seconds * RATE))


def _time(seconds):
    return np.arange(_n(seconds)) / RATE


def _rng(seed, salt=0):
    return np.random.default_rng([abs(int(seed)), salt])


def _band(signal, lo=0.0, hi=20000.0, soft=1.4):
    """Band-pass with gentle slopes, done in the frequency domain so it needs no loops or scipy."""
    spec = np.fft.rfft(signal)
    freq = np.maximum(np.fft.rfftfreq(signal.size, 1 / RATE), 1.0)
    gain = 1 / (1 + (lo / freq) ** (2 * soft)) * 1 / (1 + (freq / hi) ** (2 * soft))
    return np.fft.irfft(spec * gain, signal.size)


def _formants(signal, formants):
    """Shape a buzzy source into a vowel-like sound."""
    return sum(_band(signal, f * 0.82, f * 1.18, 2.5) / (i + 1) for i, f in enumerate(formants))


def _decay(seconds, half_life, attack=0.002):
    """An exponential decay with a very short attack, which avoids a click at the start."""
    t = _time(seconds)
    return np.minimum(t / max(attack, 1e-5), 1.0) * 0.5 ** (t / half_life)


def _partials(seconds, freqs, half_lives, gains=None):
    """A ringing body: inharmonic sine partials that each die away, as in a struck bell or bar."""
    t = _time(seconds)
    gains = gains if gains is not None else [1 / (i + 1) for i in range(len(freqs))]
    return sum(g * np.sin(2 * np.pi * f * t) * 0.5 ** (t / h) for f, h, g in zip(freqs, half_lives, gains))


def _finish(signal, peak=0.82, fade=0.004):
    """Remove any DC offset, fade the ends to avoid clicks, and set the level."""
    out = signal - signal.mean()
    if fade:
        n = min(_n(fade), out.size // 2)
        ramp = np.linspace(0.0, 1.0, n)
        out[:n] *= ramp
        out[-n:] *= ramp[::-1]
    top = np.abs(out).max()
    return (out / top * peak if top > 0 else out).astype(np.float32)


def _place(mix, sound, at):
    start = _n(at)
    end = min(mix.size, start + sound.size)
    if start < mix.size:
        mix[start:end] += sound[:end - start]


def _impact(material, rng, seconds=0.14, strength=1.0):
    """One hit on a material: filtered noise for the crunch, plus a resonance for the body."""
    wobble = rng.uniform(0.9, 1.1)
    noise = rng.normal(0, 1, _n(seconds))
    if material == "stone":
        body = _band(noise, 350 * wobble, 2600 * wobble) * _decay(seconds, 0.022)
        body += 0.8 * _band(noise, 120, 500) * _decay(seconds, 0.03)
    elif material == "wood":
        body = _band(noise, 300, 1800) * _decay(seconds, 0.012) * 0.7
        body += _partials(seconds, [190 * wobble, 410 * wobble, 760 * wobble], [0.03, 0.02, 0.012]) * 0.9
    elif material == "metal":
        body = _band(noise, 1500, 7000) * _decay(seconds, 0.006) * 0.5
        body += _partials(seconds, [830 * wobble, 1370 * wobble, 2190 * wobble, 3010 * wobble],
                          [0.07, 0.05, 0.035, 0.025], [1, 0.8, 0.5, 0.3])
    elif material == "soil":
        body = _band(noise, 90, 900 * wobble) * _decay(seconds, 0.03)
    elif material == "glass":
        body = _band(noise, 3000, 9000) * _decay(seconds, 0.005) * 0.6
        body += _partials(seconds, [2300 * wobble, 3520 * wobble, 5100 * wobble], [0.03, 0.02, 0.012])
    elif material == "plant":
        body = _band(noise, 1400, 8000) * _decay(seconds, 0.02)
    else:
        raise ValueError(f"unknown material {material!r}, expected one of {MATERIALS}")
    return body * strength


def _voice(seconds, pitch_curve, voice, rng, growl=None):
    """A buzzy vocal source with a pitch contour, jitter and roughness, shaped by the voice's formants."""
    base, rough, formants, noisy = VOICES[voice]
    n = _n(seconds)
    t = np.arange(n) / RATE
    contour = np.interp(t, np.linspace(0, seconds, len(pitch_curve)), pitch_curve)
    drift = np.interp(t, np.linspace(0, seconds, 9), rng.uniform(-0.03, 0.03, 9))
    wobble = 1 + drift + 0.012 * np.sin(2 * np.pi * rng.uniform(5, 8) * t)
    phase = 2 * np.pi * np.cumsum(base * contour * wobble) / RATE
    # A band-limited buzz: the first harmonics of a sawtooth.
    top = int(min(30, 9000 / (base * max(pitch_curve))))
    buzz = sum(np.sin(h * phase) / h for h in range(1, top + 1))
    rough = rough if growl is None else growl
    if rough > 0:  # slow amplitude flutter is what makes a voice growl
        buzz *= 1 - rough * 0.5 * (1 + np.sin(2 * np.pi * rng.uniform(22, 34) * t + rng.uniform(0, 6)))
    voiced = _formants(buzz, formants)
    breath = _band(rng.normal(0, 1, n), 900, 6000) * np.abs(voiced).mean() * 3.0
    return voiced * (1 - noisy) + breath * noisy


def _shape(seconds, points):
    """A volume curve from (time as a fraction of the sound, level) points."""
    xs, ys = zip(*points)
    return np.interp(np.linspace(0, 1, _n(seconds)), xs, ys)


# ---------------------------------------------------------------- the sounds

def block_hit(material="stone", seed=0):
    """A single soft knock, for mining or stepping on a block. About 0.15 s."""
    rng = _rng(seed, 1)
    return _finish(_impact(material, rng, 0.15))


def block_break(material="stone", seed=0):
    """A block giving way: a main crack and a few bits of rubble. About 0.45 s."""
    rng = _rng(seed, 2)
    mix = np.zeros(_n(0.45))
    _place(mix, _impact(material, rng, 0.22), 0.0)
    at = rng.uniform(0.02, 0.05)
    for i in range(int(rng.integers(3, 6))):
        _place(mix, _impact(material, rng, 0.14, strength=0.7 - i * 0.09), at)
        at += rng.uniform(0.03, 0.08)
    return _finish(mix)


def machine_hum(pitch=70.0, seed=0, seconds=1.5, rough=0.3):
    """A steady electric drone that loops without a click, because every part completes whole cycles."""
    rng = _rng(seed, 3)
    n = _n(seconds)
    t = np.arange(n) / RATE
    f0 = round(pitch * seconds) / seconds
    out = np.zeros(n)
    for h, gain in ((1, 1.0), (2, 0.55), (3, 0.28), (4, 0.18), (6, 0.08)):
        beat = round(rng.uniform(0.7, 2.2) * seconds) / seconds
        out += gain * np.sin(2 * np.pi * f0 * h * t + rng.uniform(0, 6)) * (1 + 0.14 * np.sin(2 * np.pi * beat * t))
    # Mains-style buzz: high harmonics pulsing at a whole-cycle rate, kept in the background.
    buzz = np.sin(2 * np.pi * round(f0 * 11) * t) * (0.5 + 0.5 * np.sin(2 * np.pi * f0 * 2 * t)) ** 4
    return _finish(out + rough * 0.5 * buzz, peak=0.6, fade=0)


def machine_done(pitch=880.0, seed=0):
    """A small two-note chime for a finished job. About 0.7 s."""
    rng = _rng(seed, 4)
    f = pitch * rng.uniform(0.98, 1.02)
    mix = np.zeros(_n(0.7))
    bell = lambda hz, s: _partials(s, [hz, hz * 2.01, hz * 2.76], [0.16, 0.08, 0.04], [1, 0.4, 0.2])
    _place(mix, bell(f, 0.5), 0.0)
    _place(mix, bell(f * 1.335, 0.55), 0.13)
    return _finish(mix, peak=0.7)


def item_pickup(seed=0, pitch=1.0):
    """A quick rising pop. About 0.12 s."""
    rng = _rng(seed, 5)
    seconds = 0.12
    t = _time(seconds)
    sweep = (620 + 1100 * (t / seconds) ** 0.6) * pitch * rng.uniform(0.92, 1.08)
    tone = np.sin(2 * np.pi * np.cumsum(sweep) / RATE) + 0.25 * np.sin(4 * np.pi * np.cumsum(sweep) / RATE)
    return _finish(tone * _shape(seconds, [(0, 0), (0.08, 1), (0.45, 0.7), (1, 0)]), peak=0.65)


def mob_idle(voice="grunt", seed=0, pitch=1.0):
    """A calm creature noise: one or two rounded murmurs. About 0.9 s."""
    rng = _rng(seed, 6)
    seconds = 0.9
    mix = np.zeros(_n(seconds))
    if voice == "gloop":  # a slime: wet upward bubbles
        at = 0.02
        for _ in range(int(rng.integers(2, 4))):
            s = rng.uniform(0.13, 0.2)
            up = _time(s) / s
            bubble = np.sin(2 * np.pi * np.cumsum((170 + 320 * up ** 2) * pitch * rng.uniform(0.85, 1.15)) / RATE)
            _place(mix, bubble * np.sin(np.pi * up) ** 1.5, at)
            at += s + rng.uniform(0.04, 0.16)
        return _finish(mix, peak=0.7)
    first = rng.uniform(0.34, 0.5)
    curve = [pitch * v for v in (0.95, 1.08, 1.0, 0.88)]
    _place(mix, _voice(first, curve, voice, rng) * _shape(first, [(0, 0), (0.2, 1), (0.7, 0.75), (1, 0)]), 0.02)
    if rng.random() < 0.7:
        second = rng.uniform(0.22, 0.32)
        curve = [pitch * v * rng.uniform(0.9, 1.1) for v in (1.0, 0.92, 0.82)]
        _place(mix, 0.75 * _voice(second, curve, voice, rng) * _shape(second, [(0, 0), (0.25, 1), (1, 0)]),
               0.04 + first + rng.uniform(0.02, 0.1))
    return _finish(mix, peak=0.7)


def mob_hurt(voice="grunt", seed=0, pitch=1.0):
    """A sharp yelp that falls in pitch. About 0.32 s. Rougher and higher than the idle sound."""
    rng = _rng(seed, 7)
    seconds = 0.32
    curve = [pitch * v for v in (1.5, 1.42, 1.12, 0.82)]
    base_rough = VOICES[voice][1]
    sound = _voice(seconds, curve, voice, rng, growl=min(1.0, base_rough + 0.25))
    return _finish(sound * _shape(seconds, [(0, 0), (0.06, 1), (0.5, 0.7), (1, 0)]))


def mob_death(voice="grunt", seed=0, pitch=1.0):
    """A long falling groan that loses its strength. About 1.15 s."""
    rng = _rng(seed, 8)
    seconds = 1.15
    curve = [pitch * v for v in (1.25, 1.18, 0.98, 0.76, 0.6, 0.48)]
    base_rough = VOICES[voice][1]
    sound = _voice(seconds, curve, voice, rng, growl=min(1.0, base_rough + 0.15))
    return _finish(sound * _shape(seconds, [(0, 0), (0.04, 1), (0.35, 0.8), (0.75, 0.35), (1, 0)]))


GENERATORS = {f.__name__: f for f in (block_hit, block_break, machine_hum, machine_done, item_pickup,
                                      mob_idle, mob_hurt, mob_death)}


# ---------------------------------------------------------------- writing files

def write_wav(samples, path):
    path = pathlib.Path(path).with_suffix(".wav")
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(RATE)
        out.writeframes((np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes())
    return path


def save(samples, path, quality=4):
    """Write mono audio to `path` as Ogg Vorbis and return the path actually written. Without a working
    ffmpeg this writes a .wav instead and warns: the game can't play that file."""
    if samples.ndim != 1:
        raise ValueError("sounds must be mono")
    if samples.size > MAX_SECONDS * RATE:
        raise ValueError(f"{samples.size / RATE:.2f} s is too long, the limit is {MAX_SECONDS} s")
    path = pathlib.Path(path).with_suffix(".ogg")
    path.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes()
        cmd = [ffmpeg, "-y", "-loglevel", "error", "-f", "s16le", "-ar", str(RATE), "-ac", "1", "-i", "pipe:0",
               "-c:a", "libvorbis", "-q:a", str(quality), "-ac", "1", "-map_metadata", "-1",
               "-fflags", "+bitexact", "-flags:a", "+bitexact", str(path)]
        done = subprocess.run(cmd, input=pcm, capture_output=True, check=False)
        if done.returncode == 0:
            return path
        print(f"WARNING: ffmpeg failed: {done.stderr.decode(errors='replace').strip()}", file=sys.stderr)
    else:
        print("WARNING: ffmpeg not found, so writing .wav. Minecraft can't play .wav; install ffmpeg "
              "and regenerate this sound before using it in the game.", file=sys.stderr)
    return write_wav(samples, path)


def mob_set(folder, name, voice="grunt", seed=0, pitch=1.0):
    """Write <name>_idle, <name>_hurt and <name>_death to a folder and return their paths."""
    folder = pathlib.Path(folder)
    return [save(mob_idle(voice, seed, pitch), folder / f"{name}_idle.ogg"),
            save(mob_hurt(voice, seed, pitch), folder / f"{name}_hurt.ogg"),
            save(mob_death(voice, seed, pitch), folder / f"{name}_death.ogg")]


def _coerce(text):
    for kind in (int, float):
        try:
            return kind(text)
        except ValueError:
            pass
    return text


def main(argv=None):
    parser = argparse.ArgumentParser(description="Synthesize one short game sound.")
    parser.add_argument("sound", help="sound name, or 'list'")
    parser.add_argument("-o", "--out", help="output file (default <sound>.ogg)")
    args, rest = parser.parse_known_args(argv)
    if args.sound == "list":
        for name, fn in GENERATORS.items():
            print(f"{name}{inspect.signature(fn)}")
        print(f"materials: {', '.join(MATERIALS)}\nvoices: {', '.join(VOICES)}")
        return 0
    if args.sound not in GENERATORS:
        parser.error(f"unknown sound {args.sound!r}; try 'list'")
    if len(rest) % 2:
        parser.error("options must be --name value pairs")
    kwargs = {flag.lstrip("-").replace("-", "_"): _coerce(v) for flag, v in zip(rest[::2], rest[1::2])}
    print(save(GENERATORS[args.sound](**kwargs), args.out or f"{args.sound}.ogg"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
