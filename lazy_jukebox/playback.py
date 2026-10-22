"""A two-track queue with no window and automatic SDL audio handoff."""
import os

from .config import JukeboxError


class Player:
    def __init__(self, volume):
        os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
        import pygame
        self.pygame = pygame
        try:
            pygame.mixer.init(frequency=24000, size=-16, channels=1, buffer=512)
            pygame.mixer.set_num_channels(1)
            self.channel = pygame.mixer.Channel(0)
            self.channel.set_volume(volume)
        except pygame.error as exc:
            raise JukeboxError(f"Cannot open the audio device: {exc}. Try --no-play --tracks 1 to export.") from exc

    def load(self, path):
        return self.pygame.mixer.Sound(str(path))

    def play(self, sound):
        self.channel.play(sound)

    def queue(self, sound):
        self.channel.queue(sound)

    def current(self):
        return self.channel.get_sound()

    def close(self):
        self.pygame.mixer.stop()
        self.pygame.mixer.quit()
