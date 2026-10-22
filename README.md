# The Lazy Jukebox / Endless Sloth FM

Run once, sit back, and let a local AI DJ invent ridiculous spoken-word songs.
Wonderwords collides a noun, adjective, and everyday predicament; Ollama writes
the lyrics; Piper speaks them; pydub mixes a beat; pygame plays the result while
the next track is being made. No cloud API keys, subscriptions, or runtime downloads.

## Setup

Use **64-bit Python 3.10–3.13**. Python 3.13 is tested; Python 3.14 is not yet a
supported target because audio dependencies may lack compatible wheels.
Install [Ollama](https://ollama.com/download) and [FFmpeg](https://ffmpeg.org/download.html)
(both `ffmpeg` and `ffprobe` must be on PATH).

From this directory, on Windows PowerShell:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
ollama pull llama3.2:1b
python -m piper.download_voices en_US-lessac-medium --data-dir voices
```

On macOS/Linux:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
ollama pull llama3.2:1b
python -m piper.download_voices en_US-lessac-medium --data-dir voices
```

Initial package/model installation requires internet. After that, inference and
audio playback work offline. Start `ollama serve` in another terminal if the
Ollama desktop app is not already serving. Use a downloaded local model.

A small original beat is included as `beats/sloth-hop.wav`. Add your own licensed
`.mp3`, `.wav`, or `.ogg` instrumentals to `beats/` for variety. To recreate the
demo beat if absent, run `python tools/make_demo_beat.py`.

```sh
python run_jukebox.py --check
python run_jukebox.py
```

You will see:

```text
Waking up the DJ... generating your first track. Sit back and be lazy.
Now playing #1: The sleepy toaster (34.2s)
```

Press **Ctrl+C** to stop playback, terminate the generation worker, and clean up
temporary audio. The command exits with code 130 after an interrupt.

## Controls

```sh
# Listen to exactly three songs and retain WAVs and lyrics.
python run_jukebox.py --tracks 3 --keep-tracks

# Generate one song without opening an audio device.
python run_jukebox.py --no-play

# Use a different locally installed model, voice, and beats.
python run_jukebox.py --model qwen2.5:1.5b --voice voices/en_US-lessac-high.onnx --beats ./my-beats

# Quieter playback and background music.
python run_jukebox.py --volume 0.5 --beat-gain -20
```

`--help` lists every option. `--tracks 0` is endless for playback; `--no-play`
defaults to one track and always saves output. Paths supplied on the command line
are relative to your current directory; default asset paths are relative to the
project, so launching from another directory works. `--ollama-url` only accepts
loopback HTTP addresses, and local requests bypass environment proxies and redirects.

Each saved track has its own directory under `output/session-*/` containing
`vocals.wav`, `final_song.wav`, `lyrics.txt`, and `track.json` (concept, selected
beat/model/voice, duration, and generation time). `--keep-tracks` can consume
unbounded disk space during an endless session; default playback deletes finished
tracks and removes its own session on exit. It never deletes previous sessions.

## How it behaves

- One generation process keeps the Piper voice warm and prepares one track ahead.
  The main process handles playback and remains responsive during inference.
- Short beats loop; long beats are trimmed. Vocals start after a 500 ms intro,
  with a 900 ms tail. Both sources are normalized with headroom, then the beat is
  attenuated (default -16 dB). Output is mono, 24 kHz, 16-bit WAV.
- pygame queues the next sound for automatic handoff. If generation takes longer
  than playback, a gap is unavoidable: the terminal reports that the DJ is still
  cooking, then resumes automatically. Gapless playback is not guaranteed on
  slow hardware. There is no beat alignment or pitch-based singing; this is TTS
  spoken-word comedy over a backing track.
- Only the current and next track are buffered. Lyrics are limited to 160 words,
  audio to two minutes, and Ollama uses a 2,048-token context with two CPU threads.
  These settings target modest hardware; actual RAM/latency depend on your model.
- Generation errors retry twice with a short backoff. Three consecutive failures
  stop with an error rather than hammering a broken service. Individual HTTP
  requests time out; the whole generation job also has a deadline.
- `--check` reports missing packages, FFmpeg, voices, beats, and Ollama models
  together. It does not download assets or open the audio device.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| Missing model | Run `ollama pull llama3.2:1b`, or select an installed model with `--model`. |
| Ollama unavailable | Open Ollama or run `ollama serve`. Check `ollama list`. |
| Missing voice | Download the voice and keep its `.onnx` and `.onnx.json` files together. |
| Cannot open audio device | Select a working OS output device, or use `--no-play` to export. |
| MP3 decoding fails | Ensure both FFmpeg executables are on PATH and the file is valid. |
| Slow first track / timeouts | Use a 1B model and a medium/low Piper voice; increase `--timeout 300` if needed. |
| Python 3.13 audioop error | Install the full requirements; `audioop-lts` supplies the removed stdlib module. |
| PowerShell activation blocked | Run `.\.venv\Scripts\python.exe run_jukebox.py` directly. |

## Development and checks

```sh
python -m unittest discover -s tests -v
python -m compileall -q lazy_jukebox run_jukebox.py tools
```

Tests exercise real audio mixing, loop/trim behavior, HTTP error handling,
queue overlap, bounded generation, retries, cleanup, and worker cancellation.
They use SDL's dummy audio driver where appropriate and do not download models.
For a real inference smoke test after setup:

```sh
python run_jukebox.py --no-play --tracks 1
```

The project implements [the PRD](prd_the_lazy_jukebox.md). The maintained Piper
Python wrapper is used instead of spawning its CLI for each song, which keeps the
voice loaded and makes interruption straightforward. Its documented API is
[PiperVoice.synthesize_wav](https://github.com/OHF-Voice/piper1-gpl/blob/main/docs/API_PYTHON.md).
Ollama integration follows the [generate endpoint](https://docs.ollama.com/api/generate),
and playback uses [pygame's channel queue](https://www.pygame.org/docs/ref/mixer.html#pygame.mixer.Channel.queue).

Piper and downloaded voice models have their own licenses. This repository does
not bundle any voice or LLM weights. The demo beat is synthesized by the included
source script; no third-party music samples are used.
