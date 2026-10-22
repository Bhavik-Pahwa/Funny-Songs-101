import importlib.util
import multiprocessing
import shutil
import tempfile
import time
from pathlib import Path

from .config import Config, JukeboxError
from .generation import find_beats, local_session, worker


def check_setup(config):
    """Return every discoverable setup problem, without downloading anything."""
    config.validate()
    problems = []
    for module, package in (("requests", "requests"), ("wonderwords", "wonderwords"),
                            ("pydub", "pydub"), ("pygame", "pygame"), ("piper", "piper-tts")):
        if importlib.util.find_spec(module) is None:
            problems.append(f"Missing {package}; run `python -m pip install -r requirements.txt`.")
    if importlib.util.find_spec("audioop") is None:
        problems.append("Missing audioop; install requirements.txt (includes audioop-lts on Python 3.13+).")
    for command in ("ffmpeg", "ffprobe"):
        if not shutil.which(command):
            problems.append(f"{command} is not on PATH; install FFmpeg and restart this terminal.")
    if not config.voice.is_file() or not Path(str(config.voice) + ".json").is_file():
        problems.append(f"Missing voice or its .onnx.json config: {config.voice}. "
                        "Run `python -m piper.download_voices en_US-lessac-medium --data-dir voices`.")
    if not find_beats(config.beats):
        problems.append(f"No .mp3, .wav, or .ogg beats in {config.beats}. "
                        "Add a beat or run `python tools/make_demo_beat.py`.")
    if importlib.util.find_spec("requests") is not None:
        try:
            with local_session() as session:
                response = session.get(config.ollama_url.rstrip("/") + "/api/tags",
                                       timeout=(3, 5), allow_redirects=False)
                response.raise_for_status()
                models = response.json()["models"]
                name = config.model if ":" in config.model else config.model + ":latest"
                match = next((m for m in models if m.get("name") in (config.model, name)), None)
                if match is None:
                    problems.append(f"Model {config.model} is not installed. Run `ollama pull {config.model}` once while online.")
                elif match.get("remote_model") or match.get("remote_host") or "cloud" in config.model.lower():
                    problems.append("Choose a locally downloaded model; cloud models cannot run offline.")
        except Exception as exc:
            problems.append(f"Cannot read local Ollama models ({exc}). Start `ollama serve`.")
    return problems


class Generator:
    def __init__(self, config):
        self.config = config
        context = multiprocessing.get_context("spawn")
        self.connection, child = context.Pipe()
        self.process = context.Process(target=worker, args=(child, config), daemon=True)
        self.process.start()
        child.close()
        self.started = None

    def submit(self, number, folder):
        self.connection.send((number, str(folder)))
        self.started = time.monotonic()

    def poll(self):
        if self.connection.poll():
            try:
                result = self.connection.recv()
            except EOFError as exc:
                raise JukeboxError("Generation worker exited unexpectedly.") from exc
            self.started = None
            return result
        if not self.process.is_alive():
            raise JukeboxError(f"Generation worker exited with code {self.process.exitcode}.")
        if self.started is not None and time.monotonic() - self.started > self.config.timeout + 90:
            raise JukeboxError("Track generation exceeded its time limit. Try a smaller model or increase --timeout.")
        return None

    def close(self):
        # No inference threads keep Python alive after Ctrl+C. Piper is in this
        # process too, so terminating it leaves no TTS child behind.
        if self.process.is_alive():
            self.process.terminate()
        self.process.join(timeout=3)
        if self.process.is_alive():
            self.process.kill()
            self.process.join()
        self.connection.close()
        self.process.close()


def run(config, no_play=False, log=print, player_factory=None, generator_factory=Generator):
    from .playback import Player
    player_factory = player_factory or Player
    config.output.mkdir(parents=True, exist_ok=True)
    session = Path(tempfile.mkdtemp(prefix="session-", dir=config.output)).resolve()
    keep = config.keep_tracks or no_play
    player = generator = None
    current = queued = pending = None
    generated = failures = 0
    next_attempt = 0.0
    waiting_reported = False

    def discard(folder):
        # Only delete track directories created by this run, never user paths.
        if not keep and folder.resolve().parent == session:
            shutil.rmtree(folder)

    def announce(track):
        log(f"Now playing #{track['metadata']['number']}: {track['metadata']['title']} "
            f"({track['metadata']['duration']:.1f}s)")

    try:
        if not no_play:
            player = player_factory(config.volume)
        generator = generator_factory(config)
        log("Waking up the DJ... generating your first track. Sit back and be lazy.")
        while True:
            if player and current and player.current() is not current["sound"]:
                discard(current["folder"])
                current, queued = queued, None
                if current:
                    announce(current)
                waiting_reported = False

            if pending is not None:
                result = generator.poll()
                if result is not None:
                    success, data = result
                    folder, pending = pending, None
                    if not success:
                        discard(folder)
                        failures += 1
                        if failures >= 3:
                            raise JukeboxError(f"Generation failed three times. Last error: {data}")
                        log(f"DJ hiccup: {data} Retrying in {failures * 2}s...")
                        next_attempt = time.monotonic() + failures * 2
                    else:
                        failures = 0
                        generated += 1
                        if no_play:
                            log(f"Saved #{generated}: {folder / 'final_song.wav'}")
                        else:
                            track = {"folder": folder, "metadata": data,
                                     "sound": player.load(folder / "final_song.wav")}
                            if current is None:
                                current = track
                                player.play(track["sound"])
                                announce(track)
                                waiting_reported = False
                            else:
                                queued = track
                                player.queue(track["sound"])

            limit_reached = config.tracks > 0 and generated >= config.tracks
            if limit_reached and current is None and queued is None:
                break
            if pending is None and queued is None and not limit_reached and time.monotonic() >= next_attempt:
                pending = Path(tempfile.mkdtemp(prefix=f"track-{generated + 1:04d}-", dir=session))
                generator.submit(generated + 1, pending)
            if generated and current is None and pending and not no_play and not waiting_reported:
                log("The DJ is still cooking the next track...")
                waiting_reported = True
            time.sleep(0.03)
    finally:
        if player:
            player.close()
        if generator:
            generator.close()
        if not keep:
            # session was created by mkdtemp above and is never user-supplied.
            if session.parent == config.output.resolve():
                shutil.rmtree(session)
        else:
            log(f"Tracks saved in {session}")
