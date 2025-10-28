# Video Compression API & CLI

This repository provides two main entry points for video compression:

1. **API server** (`app.py`) — A FastAPI-based service for uploading and compressing videos.
2. **CLI tool** (`compress.py`) — A command-line interface for H.265/HEVC video compression with a golden search optimization method.

---

## Requirements

- Python 3.8+
- FFmpeg installed and available in PATH
- Dependencies from `requirements.txt` (if provided) or install FastAPI and Uvicorn manually

```bash
pip install -r requirements.txt
```

---

## Running the API (`app.py`)

Start the FastAPI server with:

```bash
uvicorn app:app --reload
```

The API will expose the following endpoints:

- `GET /health` — Health check endpoint  
- `POST /compress` — Upload a single video and receive compressed output  
- `POST /batch_compress` — Upload multiple videos and receive a ZIP of compressed outputs  
- `GET /config` — Fetch the active configuration  

---

## Running the CLI (`compress.py`)

The CLI can be run directly to compress videos from the command line:

```bash
python compress.py --input input_video.mp4 --output output_video.mp4
```

Arguments:
- `--input` : Path to input video file  
- `--output` : Path to output video file (extension will match input format)  
- `--config` *(optional)* : Path to configuration file (default: `config.json`)  

Example:

```bash
python compress.py --input sample.mp4 --output compressed.mp4
```

---

## Notes

- Both the API and CLI use the same compression backend (`H265Compressor` class).
- Configuration details are stored in `config.json` but **you do not need to modify it to run the tools**.
- Make sure FFmpeg is installed and accessible in your environment.

---
