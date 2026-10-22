import json
import os
import tempfile
import threading
import time
import unittest
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock, patch

os.environ["SDL_AUDIODRIVER"] = "dummy"
os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"

from pydub import AudioSegment
from pydub.generators import Sine

from lazy_jukebox.app import Generator, run
from lazy_jukebox.config import Config, JukeboxError
from lazy_jukebox.generation import Concept, clean_lyrics, collide, find_beats, mix_track, write_lyrics
from lazy_jukebox.playback import Player


def save_audio(audio, path):
    with audio.export(path, format="wav"):
        pass


def read_audio(path):
    with path.open("rb") as source:
        return AudioSegment.from_wav(source)


class ConfigTests(unittest.TestCase):
    def test_only_loopback_urls(self):
        for url in ("http://localhost:11434", "http://127.0.0.1:11434", "http://[::1]:11434"):
            Config(ollama_url=url).validate()
        for url in ("https://example.com", "http://example.com", "http://localhost@evil.test",
                    "http://localhost/other", "http://localhost:bad", "http://localhost?redirect=x", "http://["):
            with self.subTest(url=url), self.assertRaises(JukeboxError):
                Config(ollama_url=url).validate()

    def test_invalid_numbers(self):
        for field, value in (("volume", 2), ("tracks", -1), ("timeout", 0),
                             ("beat_gain", 1), ("volume", float("nan")), ("timeout", float("inf"))):
            with self.subTest(field=field), self.assertRaises(JukeboxError):
                replace(Config(), **{field: value}).validate()

    def test_concept_uses_word_categories(self):
        words = Mock()
        words.word.side_effect = ["toaster", "sleepy"]
        concept = collide(words, Mock(choice=Mock(return_value="doing taxes")))
        self.assertEqual(concept.title, "The sleepy toaster")
        self.assertIn("sleepy toaster doing taxes", concept.prompt)
        self.assertEqual(words.word.call_args_list[0].kwargs["include_parts_of_speech"], ["nouns"])

    def test_lyrics_cleanup_and_bounds(self):
        text = "<think>private reasoning</think>\n[Verse 1]\n# Chorus\n" + "toast " * 200
        cleaned = clean_lyrics(text)
        self.assertEqual(len(cleaned.split()), 160)
        self.assertNotIn("think", cleaned)
        for bad in ("", None, "[Verse 1]", "hi"):
            with self.assertRaises(JukeboxError):
                clean_lyrics(bad)


class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.status, cls.body, cls.delay, cls.request = 200, {}, 0, None
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                cls.request = (self.path, json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                time.sleep(cls.delay)
                self.send_response(cls.status)
                self.end_headers()
                try:
                    self.wfile.write(json.dumps(cls.body).encode())
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    pass
            def log_message(self, *args):
                pass
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def setUp(self):
        type(self).status, type(self).delay = 200, 0
        type(self).body = {"response": "My toaster wore a tie today and burned my bills away"}
        self.config = Config(ollama_url=self.url)
        self.concept = Concept("toaster", "sleepy", "doing taxes")

    def test_real_http_payload_and_response(self):
        lyrics = write_lyrics(self.config, self.concept)
        self.assertIn("toaster", lyrics)
        path, payload = self.request
        self.assertEqual(path, "/api/generate")
        self.assertFalse(payload["stream"])
        self.assertEqual(payload["options"]["num_ctx"], 2048)

    def test_http_error_and_bad_payload(self):
        for status, body in ((500, {}), (200, {"error": "bad model"}), (200, []), (200, {"response": ""})):
            type(self).status, type(self).body = status, body
            with self.subTest(status=status, body=body), self.assertRaises(JukeboxError):
                write_lyrics(self.config, self.concept)

    def test_request_timeout(self):
        type(self).delay = 0.2
        with self.assertRaises(JukeboxError):
            write_lyrics(replace(self.config, timeout=0.03), self.concept)

    def test_worker_cancels_during_inference(self):
        type(self).delay = 5
        type(self).request = None
        with tempfile.TemporaryDirectory() as folder:
            generator = Generator(self.config)
            try:
                generator.submit(1, folder)
                deadline = time.monotonic() + 8
                while self.request is None and time.monotonic() < deadline:
                    time.sleep(0.03)
                self.assertIsNotNone(self.request)
                started = time.monotonic()
            finally:
                generator.close()
            self.assertLess(time.monotonic() - started, 3)


class AudioTests(unittest.TestCase):
    def test_short_and_long_beats_preserve_vocals_and_headroom(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            save_audio(Sine(440).to_audio_segment(duration=1800), root / "vocals.wav")
            for duration in (200, 5000):
                save_audio(Sine(70).to_audio_segment(duration=duration), root / "beat.wav")
                length = mix_track(root / "vocals.wav", root / "beat.wav", root / "song.wav", gain=0)
                song = read_audio(root / "song.wav")
                self.assertEqual(length, 3.2)
                self.assertEqual(len(song), 3200)
                self.assertEqual((song.frame_rate, song.channels, song.sample_width), (24000, 1, 2))
                self.assertLess(song.max, 32767)
                self.assertGreater(song[2800:3000].rms, 0)

    def test_mp3_beat_decoding(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            save_audio(Sine(440).to_audio_segment(duration=500), root / "vocals.wav")
            with Sine(70).to_audio_segment(duration=200).export(root / "beat.mp3", format="mp3"):
                pass
            mix_track(root / "vocals.wav", root / "beat.mp3", root / "song.wav")
            self.assertEqual(len(read_audio(root / "song.wav")), 1900)

    def test_silent_beat_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            save_audio(Sine(440).to_audio_segment(duration=500), root / "vocals.wav")
            save_audio(AudioSegment.silent(duration=300), root / "beat.wav")
            with self.assertRaises(JukeboxError):
                mix_track(root / "vocals.wav", root / "beat.wav", root / "song.wav")

    def test_beat_discovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("yes.MP3", "yes.wav", "yes.ogg", "no.txt"):
                (root / name).touch()
            (root / "directory.mp3").mkdir()
            self.assertEqual(len(find_beats(root)), 3)

    def test_real_pygame_queue_handoff(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tone.wav"
            save_audio(Sine(200).to_audio_segment(duration=180), path)
            player = Player(0.0)
            try:
                first, second = player.load(path), player.load(path)
                player.play(first)
                player.queue(second)
                self.assertIs(player.current(), first)
                seen_second = False
                deadline = time.monotonic() + 2
                while player.current() is not None and time.monotonic() < deadline:
                    seen_second |= player.current() is second
                    time.sleep(0.01)
                self.assertTrue(seen_second)
                self.assertIsNone(player.current())
            finally:
                player.close()


class LoopTests(unittest.TestCase):
    def simulate(self, root, *, fail=False, no_play=False, interrupt=False, slow=False, keep=False):
        clock = [0.0]
        state = {"overlap": False, "submitted": 0, "max_folders": 0, "closed": 0}

        class FakePlayer:
            def __init__(self, volume):
                self.sound, self.queued, self.end = None, None, 0
            def load(self, path):
                return object()
            def play(self, sound):
                self.sound, self.end = sound, clock[0] + 1
            def queue(self, sound):
                self.queued = sound
            def current(self):
                if clock[0] >= self.end:
                    self.sound, self.queued = self.queued, None
                    self.end = clock[0] + 1
                return self.sound
            def close(self):
                state["closed"] += 1

        player = FakePlayer(0)

        class FakeGenerator:
            def __init__(self, config):
                pass
            def submit(self, number, folder):
                self.number, self.ready = number, clock[0] + (1.5 if slow else 0.2)
                state["submitted"] += 1
                state["overlap"] |= player.current() is not None
                state["max_folders"] = max(state["max_folders"], len(list(root.glob("session-*/track-*"))))
                (folder / "final_song.wav").touch()
            def poll(self):
                if interrupt:
                    raise KeyboardInterrupt
                if clock[0] < self.ready:
                    return None
                if fail:
                    return False, "simulated failure"
                return True, {"number": self.number, "title": "Test track", "duration": 1.0}
            def close(self):
                state["closed"] += 1

        def tick(seconds):
            clock[0] += seconds
            if clock[0] > 20:
                raise AssertionError("Loop did not finish")
        messages = []
        with patch("lazy_jukebox.app.time.monotonic", lambda: clock[0]), patch("lazy_jukebox.app.time.sleep", tick):
            run(Config(output=root, tracks=4, keep_tracks=keep), no_play=no_play, log=messages.append,
                player_factory=lambda volume: player, generator_factory=FakeGenerator)
        return state, messages

    def test_generation_overlaps_playback_and_stays_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state, messages = self.simulate(root)
            self.assertTrue(state["overlap"])
            self.assertEqual(state["submitted"], 4)
            self.assertLessEqual(state["max_folders"], 2)
            self.assertEqual(state["closed"], 2)
            self.assertEqual(len([m for m in messages if m.startswith("Now playing")]), 4)
            self.assertEqual(list(root.iterdir()), [])

    def test_slow_generation_recovers(self):
        with tempfile.TemporaryDirectory() as tmp:
            state, messages = self.simulate(Path(tmp), slow=True)
            self.assertEqual(state["submitted"], 4)
            self.assertTrue(any("still cooking" in m for m in messages))

    def test_render_only_retains_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state, _ = self.simulate(root, no_play=True)
            self.assertEqual(len(list(root.glob("session-*/track-*/final_song.wav"))), 4)
            self.assertEqual(state["closed"], 1)

    def test_keep_tracks_retains_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.simulate(root, keep=True)
            self.assertEqual(len(list(root.glob("session-*/track-*/final_song.wav"))), 4)

    def test_repeated_failure_cleans_session_but_not_existing_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "existing.txt").write_text("keep me")
            with self.assertRaisesRegex(JukeboxError, "three times"):
                self.simulate(root, fail=True)
            self.assertEqual([p.name for p in root.iterdir()], ["existing.txt"])

    def test_interrupt_cleans_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(KeyboardInterrupt):
                self.simulate(root, interrupt=True)
            self.assertEqual(list(root.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
