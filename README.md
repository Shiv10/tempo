# Tempo

Automatically removes all pauses and silences from a video. One command, clean output.

## Requirements

```bash
brew install ffmpeg
```

## Usage

```bash
# Basic — removes all pauses (outputs: your_video_cut.mp4)
python3 silence_cut.py your_video.mp4

# Specify output file
python3 silence_cut.py your_video.mp4 -o final.mp4

# Presets
python3 silence_cut.py your_video.mp4 --preset aggressive  # cut everything, tight pacing
python3 silence_cut.py your_video.mp4 --preset balanced    # default
python3 silence_cut.py your_video.mp4 --preset gentle      # only long dead air

# Preview what will be cut without producing a file
python3 silence_cut.py your_video.mp4 --dry-run --verbose

# Manual tuning
python3 silence_cut.py your_video.mp4 -t -40 -d 0.3 -m 0.1
```

## Options

| Flag | Description | Default |
|---|---|---|
| `-o` | Output file path | `<input>_cut.mp4` |
| `-t` | Silence threshold in dB (more negative = stricter) | `-35` |
| `-d` | Minimum pause duration to cut (seconds) | `0.4` |
| `-m` | Audio padding kept at edges of each cut (seconds) | `0.05` |
| `--preset` | `aggressive` / `balanced` / `gentle` | `balanced` |
| `--dry-run` | Report only, no output file | |
| `--no-hw` | Disable hardware acceleration | |
| `-v` | Print every detected silence and speech interval | |

## How it works

See [HOW_IT_WORKS.md](HOW_IT_WORKS.md) for a full plain-English walkthrough.
