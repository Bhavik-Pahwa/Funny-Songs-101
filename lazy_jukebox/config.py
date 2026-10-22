from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit
import ipaddress
import math

ROOT = Path(__file__).resolve().parent.parent


class JukeboxError(Exception):
    """An actionable setup or generation error."""


@dataclass(frozen=True)
class Config:
    model: str = "llama3.2:1b"
    ollama_url: str = "http://127.0.0.1:11434"
    voice: Path = ROOT / "voices" / "en_US-lessac-medium.onnx"
    beats: Path = ROOT / "beats"
    output: Path = ROOT / "output"
    beat_gain: float = -16.0
    volume: float = 0.8
    timeout: float = 180.0
    tracks: int = 0
    keep_tracks: bool = False

    def validate(self):
        try:
            url = urlsplit(self.ollama_url)
        except ValueError as exc:
            raise JukeboxError("Ollama URL is malformed; use http://127.0.0.1:11434.") from exc
        try:
            loopback = url.hostname == "localhost" or ipaddress.ip_address(url.hostname or "").is_loopback
        except ValueError:
            loopback = False
        if (url.scheme != "http" or not loopback or url.username or url.password
                or url.path not in ("", "/") or url.query or url.fragment):
            raise JukeboxError("Ollama URL must be a local HTTP address, e.g. http://127.0.0.1:11434.")
        try:
            url.port
        except ValueError as exc:
            raise JukeboxError("Ollama URL contains an invalid port.") from exc
        if not self.model.strip():
            raise JukeboxError("Choose an installed Ollama model with --model.")
        if self.tracks < 0:
            raise JukeboxError("--tracks must be 0 (endless) or a positive integer.")
        if not math.isfinite(self.volume) or not 0 <= self.volume <= 1:
            raise JukeboxError("--volume must be between 0 and 1.")
        if not math.isfinite(self.beat_gain) or not -60 <= self.beat_gain <= 0:
            raise JukeboxError("--beat-gain must be between -60 and 0 dB.")
        if not math.isfinite(self.timeout) or self.timeout <= 0:
            raise JukeboxError("--timeout must be a positive number of seconds.")
