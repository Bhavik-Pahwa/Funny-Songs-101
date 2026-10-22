# Product Requirements Document (PRD)

**Project Name:** The Lazy Jukebox (or *Endless Sloth FM*)
**Hacktoberfest Theme Alignment:** "Slow and Steady" / Laziness. The user runs the script once, sits back, and the machine handles all the creative thinking, writing, speaking, and DJing indefinitely.

## 1. Overview & Goal
A completely offline, local CLI application that endlessly generates and plays funny, spoken-word "songs" (vocals mixed with a background beat) to cure music boredom without requiring any ongoing user input. Designed to run efficiently on lower-spec hardware (8GB RAM, integrated graphics).

## 2. User Flow
1. User executes `python run_jukebox.py` in their terminal.
2. The terminal displays: *"Waking up the DJ... generating your first track. Sit back and be lazy."*
3. The app generates the first track, plays it out loud automatically, and simultaneously starts generating the next track in the background.
4. The user listens indefinitely until they manually terminate the script (Ctrl+C).

## 3. Core Features (Minimum Viable Product)
*   **Concept Collider (Idea Generator):** A Python function that grabs 1 random noun, 1 random adjective, and 1 random scenario to form a unique prompt.
*   **Lyric Writer:** A local API call to Ollama running a lightweight model (e.g., Llama 3.2 1B) passing the prompt to generate a short, funny rap or poem.
*   **Vocal Synthesis:** Passing the generated lyrics to the Piper TTS CLI/Python wrapper to generate a local `vocals.wav` file.
*   **The DJ Mixer:** Using the `pydub` library to load a random `.mp3` beat from a local `/beats` directory, overlaying the `vocals.wav` on top of it, and exporting the result as `final_song.wav`.
*   **Auto-Player:** Using `pygame.mixer` to play `final_song.wav` seamlessly.

## 4. System Requirements & Setup
*   **Target Hardware:** 8GB RAM, Intel Iris integrated GPU.
*   **OS:** Windows, macOS, or Linux.
*   **Core Dependencies:**
    *   **LLM Engine:** `ollama` installed locally with the `llama3.2:1b` (or `qwen2.5:1.5b`) model pulled.
    *   **TTS Engine:** `piper-tts` downloaded with a fast, expressive voice model (e.g., `en_US-lessac-high`).
    *   **Audio Backend:** *FFmpeg* installed on the host system (required by pydub for audio manipulation).
    *   **Python Packages:** 
        *   `wonderwords` (for random word generation)
        *   `pydub` (for audio mixing)
        *   `pygame` (for audio playback)
        *   `requests` (to communicate with the local Ollama API)

## 5. Implementation Steps (Hackathon Scope)
1.  **Step 1: The Prompter.** Write a Python script to generate the funny prompt using `wonderwords` (e.g., "A song about a [adjective] [noun] [doing a mundane task]").
2.  **Step 2: The Writer.** Create a function that sends the generated prompt to `http://localhost:11434/api/generate` (Ollama's local API) and extracts the raw lyrics string from the response.
3.  **Step 3: The Singer.** Write a function that uses Python's `subprocess` module to call the Piper TTS executable, passing the lyrics string and outputting a `vocals.wav` file.
4.  **Step 4: The Mixer.** Write a function using `pydub.AudioSegment` to combine `vocals.wav` with a random local file (e.g., `beat1.mp3`). Reduce the beat volume slightly so the vocals remain clear and punchy.
5.  **Step 5: The Lazy Loop.** Wrap the entire process in a `while True:` loop. Structure the loop so that while `pygame.mixer` is playing the current track, the script is silently generating the next one.