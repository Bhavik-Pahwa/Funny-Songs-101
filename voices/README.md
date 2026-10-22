Download a Piper voice once while online:

```sh
python -m piper.download_voices en_US-lessac-medium --data-dir voices
```

Keep both `en_US-lessac-medium.onnx` and `en_US-lessac-medium.onnx.json` together.
Use `--voice /path/to/another-voice.onnx` to choose another voice. Medium quality
is the default for a modest CPU/memory footprint. High quality also works.
Voice models have their own licenses; consult their model cards before redistribution.
