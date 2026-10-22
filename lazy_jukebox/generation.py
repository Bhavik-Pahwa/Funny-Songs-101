"""All expensive work happens in one separate, cancellable process."""
import json
import random
import re
import signal
import time
import wave
from dataclasses import dataclass
from pathlib import Path

from .config import Config, JukeboxError

SCENARIOS = (
    "arguing with a self-checkout machine", "folding a mountain of laundry",
    "trying to cancel a gym membership", "waiting for a software update",
    "hunting for the missing TV remote", "hosting a meeting that could have been an email",
    "trying to assemble flat-pack furniture", "negotiating with a stubborn toaster",
    "taking the bins out in slippers", "forgetting why they entered the kitchen",
    "pretending to understand a tax form", "fighting a fitted bedsheet",
    "ordering one very complicated coffee", "watering a plastic houseplant",
    "trying to remember a password", "training for the competitive napping finals",
)


@dataclass(frozen=True)
class Concept:
    noun: str
    adjective: str
    scenario: str

    @property
    def title(self):
        return f"The {self.adjective} {self.noun}"

    @property
    def prompt(self):
        return (f"Write a funny spoken-word rap about a {self.adjective} {self.noun} "
                f"{self.scenario}. Write 8 to 12 short rhyming lines, at most 120 words. "
                "Include an absurd twist and a catchy repeated line. Keep it playful and "
                "family-friendly. Output only the words to speak: no title, headings, "
                "markdown, stage directions, explanations, or sound effects.")


def collide(words=None, rng=None):
    if words is None:
        from wonderwords import RandomWord
        words = RandomWord()
    rng = rng or random
    return Concept(words.word(include_parts_of_speech=["nouns"]),
                   words.word(include_parts_of_speech=["adjectives"]), rng.choice(SCENARIOS))


def clean_lyrics(text):
    if not isinstance(text, str):
        raise JukeboxError("Ollama returned a non-text response.")
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    text = re.sub(r"\[[^\]]*\]", "", text)
    text = re.sub(r"(?im)^\s*(?:verse|chorus|intro|outro|bridge|title)\b[^\n]*", "", text)
    text = re.sub(r"[*#`]", "", text).strip()
    if not text or len(text.split()) < 8:
        raise JukeboxError("Ollama returned empty or unusable lyrics; trying another concept.")
    # Bound synthesis duration and memory even if a model ignores the prompt.
    return " ".join(text.split()[:160])


def local_session():
    import requests
    session = requests.Session()
    session.trust_env = False  # Never send local inference through an environment proxy.
    return session


def write_lyrics(config, concept):
    import requests
    try:
        with local_session() as session:
            response = session.post(config.ollama_url.rstrip("/") + "/api/generate", json={
                "model": config.model, "prompt": concept.prompt, "stream": False,
                "keep_alive": "5m",
                "options": {"temperature": 0.95, "num_predict": 240,
                            "num_ctx": 2048, "num_thread": 2},
            }, timeout=(5, config.timeout), allow_redirects=False)
            if response.status_code != 200:
                raise JukeboxError(f"Ollama returned HTTP {response.status_code}. Check `ollama list` and the server.")
            payload = response.json()
            if not isinstance(payload, dict) or payload.get("error"):
                raise JukeboxError(f"Ollama generation failed: {str(payload)[:300]}")
            return clean_lyrics(payload.get("response"))
    except requests.exceptions.JSONDecodeError as exc:
        raise JukeboxError("Ollama returned invalid JSON.") from exc
    except requests.RequestException as exc:
        raise JukeboxError("Cannot generate lyrics. Start `ollama serve` or increase --timeout.") from exc
    except ValueError as exc:
        raise JukeboxError("Ollama returned invalid JSON.") from exc


def find_beats(directory):
    return sorted(p for p in directory.glob("*") if p.is_file() and p.suffix.lower() in {".mp3", ".wav", ".ogg"})


def mix_track(vocals_path, beat_path, destination, gain=-16.0):
    from pydub import AudioSegment, effects
    with wave.open(str(vocals_path), "rb") as wav:
        if wav.getnframes() / wav.getframerate() > 120:
            raise JukeboxError("Piper produced more than two minutes of audio; refusing an oversized track.")
        vocals = AudioSegment(wav.readframes(wav.getnframes()), sample_width=wav.getsampwidth(),
                              frame_rate=wav.getframerate(), channels=wav.getnchannels())
    vocals = vocals.set_frame_rate(24000).set_channels(1).set_sample_width(2)
    if not len(vocals) or vocals.rms == 0:
        raise JukeboxError("Piper produced empty or silent vocals.")
    # Decode only what can be used; do not load a multi-hour beat into memory.
    duration = len(vocals) + 1400
    if beat_path.suffix.lower() == ".wav":
        # pydub's WAV fast path reads the whole file before applying duration.
        with wave.open(str(beat_path), "rb") as wav:
            beat = AudioSegment(wav.readframes(int(wav.getframerate() * duration / 1000)),
                                sample_width=wav.getsampwidth(), frame_rate=wav.getframerate(),
                                channels=wav.getnchannels())
    else:
        beat = AudioSegment.from_file(beat_path, duration=duration / 1000)
    beat = beat.set_frame_rate(24000).set_channels(1).set_sample_width(2)
    if not len(beat) or beat.rms == 0:
        raise JukeboxError(f"Beat is empty or silent: {beat_path.name}")
    bed = (effects.normalize(beat, headroom=8) * ((duration // len(beat)) + 1))[:duration]
    bed = (bed + gain).fade_in(150).fade_out(600)
    # Reserve headroom before overlay; normalization cannot undo clipping.
    song = bed.overlay(effects.normalize(vocals, headroom=8), position=500)
    with song.export(destination, format="wav"):
        pass
    return len(song) / 1000


def worker(connection, config):
    """Keep Piper warm, accept exactly one requested track at a time."""
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    voice = None
    try:
        while True:
            task = connection.recv()
            if task is None:
                return
            number, folder = task
            folder = Path(folder)
            started = time.monotonic()
            try:
                concept = collide()
                lyrics = write_lyrics(config, concept)
                if voice is None:
                    from piper import PiperVoice
                    voice = PiperVoice.load(str(config.voice), use_cuda=False)
                with wave.open(str(folder / "vocals.wav"), "wb") as wav:
                    voice.synthesize_wav(lyrics, wav)
                beats = find_beats(config.beats)
                if not beats:
                    raise JukeboxError(f"No beats found in {config.beats}.")
                beat = random.choice(beats)
                duration = mix_track(folder / "vocals.wav", beat, folder / "final_song.wav", config.beat_gain)
                metadata = {"number": number, "title": concept.title, "scenario": concept.scenario,
                            "lyrics": lyrics, "beat": beat.name, "model": config.model,
                            "voice": config.voice.name, "duration": duration,
                            "generation_seconds": round(time.monotonic() - started, 2)}
                (folder / "track.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
                (folder / "lyrics.txt").write_text(lyrics + "\n", encoding="utf-8")
                connection.send((True, metadata))
            except Exception as exc:
                connection.send((False, f"{type(exc).__name__}: {exc}"))
    except (EOFError, BrokenPipeError):
        pass
    finally:
        connection.close()
