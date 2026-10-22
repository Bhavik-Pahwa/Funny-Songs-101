import argparse
import sys
from pathlib import Path

from .config import Config, JukeboxError


def main(argv=None):
    defaults = Config()
    parser = argparse.ArgumentParser(description="The Lazy Jukebox / Endless Sloth FM: offline comedy radio.")
    parser.add_argument("--model", default=defaults.model, help="Installed Ollama model (default: llama3.2:1b)")
    parser.add_argument("--ollama-url", default=defaults.ollama_url, help="Local Ollama HTTP address")
    parser.add_argument("--voice", type=Path, default=defaults.voice, help="Piper .onnx model path")
    parser.add_argument("--beats", type=Path, default=defaults.beats, help="Directory of .mp3, .wav, or .ogg beats")
    parser.add_argument("--output", type=Path, default=defaults.output, help="Working/output directory")
    parser.add_argument("--beat-gain", type=float, default=defaults.beat_gain, help="Beat gain in dB, -60 to 0 (default: -16)")
    parser.add_argument("--volume", type=float, default=defaults.volume, help="Playback volume, 0 to 1 (default: 0.8)")
    parser.add_argument("--timeout", type=float, default=defaults.timeout, help="Ollama timeout in seconds")
    parser.add_argument("--tracks", type=int, default=0, help="Stop after N tracks; 0 means endless (default)")
    parser.add_argument("--keep-tracks", action="store_true", help="Keep generated WAVs, lyrics, and metadata")
    parser.add_argument("--no-play", action="store_true", help="Export without an audio device; defaults to one track")
    parser.add_argument("--check", action="store_true", help="Check dependencies and local assets, then exit")
    args = vars(parser.parse_args(argv))
    check, no_play = args.pop("check"), args.pop("no_play")
    if no_play and args["tracks"] == 0:
        args["tracks"] = 1
    for key in ("voice", "beats", "output"):
        args[key] = args[key].expanduser().resolve()
    try:
        from .app import check_setup, run
        config = Config(**args)
        problems = check_setup(config)
        if problems:
            print("The DJ needs a little setup:", file=sys.stderr)
            for problem in problems:
                print(f"  - {problem}", file=sys.stderr)
            return 1
        if check:
            print("Ready: local Ollama model, Piper voice, beats, FFmpeg, and Python packages found.")
            print("Audio output is checked when playback starts.")
            return 0
        run(config, no_play=no_play)
        return 0
    except KeyboardInterrupt:
        print("\nThe DJ is going back to sleep. Goodbye!")
        return 130
    except (JukeboxError, OSError, ImportError) as exc:
        print(f"The DJ stopped: {exc}", file=sys.stderr)
        return 1
