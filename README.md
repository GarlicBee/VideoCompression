# Video Compression Algorithm Testing Matrix

A comprehensive Python framework for evaluating and comparing multiple video compression algorithms using VMAF quality metrics and compression ratio analysis.

## 🎯 Overview

This system automatically tests multiple compression algorithms on a collection of videos, generating:
- **VMAF Quality Matrices** - Perceptual quality scores for each algorithm-video combination
- **Compression Ratio Matrices** - Size reduction efficiency for each combination
- **Statistical Summaries** - Average performance metrics and rankings

## 📁 Project Structure

```
project/
├── config.ini                 # Main configuration file
├── matrix.py                  # Core matrix generation script
├── README.md                  # This documentation
├── test_videos/              # Your test video files
│   ├── video1.mp4
│   ├── video2.mov
│   └── video3.webm
├── algorithms/               # Algorithm implementations
│   ├── h264_high/
│   │   ├── compress.py       # Required: compression script
│   │   ├── config.json       # Required: algorithm config
│   │   ├── requirements.txt  # Required: dependencies
│   │   └── README.md         # Optional: documentation
│   ├── h265_medium/
│   └── av1_experimental/
├── output_videos/            # Generated compressed videos
│   ├── h264_high/
│   ├── h265_medium/
│   └── av1_experimental/
└── results/                  # Final analysis results
    ├── vmaf_matrix.csv       # VMAF scores matrix
    ├── compression_matrix.csv # Compression ratios matrix
    └── summary.json          # Statistical summary
```

## 🚀 Quick Start

### 1. Installation

```bash
# Install Python dependencies
pip install numpy pandas opencv-python ffmpeg-python

# Install FFmpeg with VMAF support
# Ubuntu/Debian:
sudo apt install ffmpeg

# macOS:
brew install ffmpeg

# Windows: Download from https://ffmpeg.org/
```

### 2. Setup

1. **Place your test videos** in the `test_videos/` directory
   - Supported formats: `.mov`, `.mp4`, `.webm`, `.mvi`, `.mkv`, `.avi`

2. **Create algorithm implementations** in the `algorithms/` directory
   - Each algorithm needs its own folder with required files

3. **Configure settings** in `config.ini` (see Configuration section)

### 3. Run

```bash
python matrix.py
```

## ⚙️ Configuration (config.ini)

```ini
# Number of algorithms to test (-1 = all discovered)
NO_OF_ALGORITHMS=-1

# Number of videos to test (-1 = all discovered)  
NO_OF_VIDEOS=-1

# Directory paths
VIDEO_PATH=./test_videos
ALGO_PATH=./algorithms
OUTPUT_VIDEO_PATH=./output_videos

# VMAF settings
VMAF_MODEL_PATH=
VMAF_THREADS=4

# Supported video formats
SUPPORTED_FORMATS=mov,mp4,webm,mvi,mkv,avi
```

## 🔧 Creating Algorithm Implementations

Each algorithm folder must contain these **required files**:

### 1. compress.py
Main compression script with standardized interface:

```python
#!/usr/bin/env python3
import argparse
import json
import subprocess
import sys
from pathlib import Path

class VideoCompressor:
    def __init__(self, config_file="config.json"):
        self.config = self._load_config(config_file)

    def _load_config(self, config_file):
        config_path = Path(__file__).parent / config_file
        if config_path.exists():
            with open(config_path, 'r') as f:
                return json.load(f)
        return {}

    def compress(self, input_video, output_video):
        """
        Main compression function - IMPLEMENT THIS

        Args:
            input_video (str): Path to input video
            output_video (str): Path to output video

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            Path(output_video).parent.mkdir(parents=True, exist_ok=True)

            # YOUR COMPRESSION IMPLEMENTATION HERE
            # Example: H.264 compression
            cmd = [
                'ffmpeg', '-y',
                '-i', input_video,
                '-c:v', 'libx264',
                '-preset', self.config.get('preset', 'medium'),
                '-crf', str(self.config.get('crf', 23)),
                '-c:a', 'aac',
                output_video
            ]

            result = subprocess.run(cmd, capture_output=True, text=True)
            return result.returncode == 0

        except Exception as e:
            print(f"Compression error: {e}")
            return False

def main():
    parser = argparse.ArgumentParser(description='Video compression algorithm')
    parser.add_argument('--input', required=True, help='Input video file')
    parser.add_argument('--output', required=True, help='Output video file')
    parser.add_argument('--config', default='config.json', help='Config file')

    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"Error: Input file {args.input} not found!")
        sys.exit(1)

    compressor = VideoCompressor(args.config)
    success = compressor.compress(args.input, args.output)
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
```

### 2. config.json
Algorithm metadata and parameters:

```json
{
  "algorithm_name": "H.264 High Quality",
  "algorithm_type": "traditional",
  "description": "H.264 compression with high quality settings",
  "author": "Your Name",
  "version": "1.0.0",
  "parameters": {
    "preset": "slow",
    "crf": 18,
    "profile": "high"
  },
  "supported_formats": ["mp4", "mov", "avi", "mkv"],
  "output_format": "mp4",
  "expected_compression_ratio": 5.0,
  "quality_target": "high"
}
```

### 3. requirements.txt
Python dependencies:

```txt
opencv-python>=4.5.0
numpy>=1.21.0
ffmpeg-python>=0.2.0
```

## 📊 Output Results

The system generates several output files:

### VMAF Matrix (vmaf_matrix.csv)
```csv
,h264_high,h265_medium,av1_experimental
video1,85.2,87.5,89.1
video2,82.1,84.3,86.7
video3,88.9,90.2,91.8
```

### Compression Matrix (compression_matrix.csv)  
```csv
,h264_high,h265_medium,av1_experimental
video1,4.2,6.8,8.1
video2,3.9,6.2,7.5
video3,5.1,7.3,8.9
```

### Summary Statistics (summary.json)
```json
{
  "total_videos": 3,
  "total_algorithms": 3,
  "video_names": ["video1", "video2", "video3"],
  "algorithm_names": ["h264_high", "h265_medium", "av1_experimental"],
  "average_vmaf_per_algorithm": {
    "h264_high": 85.4,
    "h265_medium": 87.3,
    "av1_experimental": 89.2
  },
  "average_compression_per_algorithm": {
    "h264_high": 4.4,
    "h265_medium": 6.8,
    "av1_experimental": 8.2
  }
}
```

## 🎬 Algorithm Examples

### H.264 Implementation
```python
# In compress.py
cmd = [
    'ffmpeg', '-y',
    '-i', input_video,
    '-c:v', 'libx264',
    '-preset', 'slow',
    '-crf', '18',
    '-c:a', 'aac',
    output_video
]
```

### H.265/HEVC Implementation
```python
cmd = [
    'ffmpeg', '-y', 
    '-i', input_video,
    '-c:v', 'libx265',
    '-preset', 'medium',
    '-crf', '28',
    '-c:a', 'aac',
    output_video
]
```

### AV1 Implementation
```python
cmd = [
    'ffmpeg', '-y',
    '-i', input_video,
    '-c:v', 'libaom-av1',
    '-cpu-used', '4',
    '-crf', '32',
    '-c:a', 'libopus',
    output_video
]
```

## 🔍 Features

- **🎯 Automatic Discovery**: Finds videos and algorithms automatically
- **📊 VMAF Scoring**: Industry-standard perceptual quality measurement
- **⚡ Parallel Processing**: Configurable threading for VMAF calculations
- **🛡️ Error Handling**: Robust error handling with timeouts and validation
- **📈 Progress Tracking**: Detailed logging and real-time statistics
- **💾 Multiple Formats**: Support for all major video formats
- **🔧 Extensible**: Easy to add new algorithms and metrics
- **📋 Export Options**: CSV matrices and JSON summaries

## 🚨 Troubleshooting

### Common Issues

1. **FFmpeg not found**
   ```bash
   # Install FFmpeg with VMAF support
   sudo apt install ffmpeg  # Ubuntu
   brew install ffmpeg      # macOS
   ```

2. **VMAF calculation fails**
   - Ensure FFmpeg has VMAF filter support
   - Check video format compatibility
   - Verify sufficient disk space for temporary files

3. **Algorithm timeout**
   - Increase timeout in `run_algorithm()` method
   - Check algorithm implementation for infinite loops
   - Monitor system resources during processing

4. **No videos/algorithms discovered**
   - Check directory paths in `config.ini`
   - Verify file permissions
   - Ensure algorithm folders have required files

### Debug Mode
```bash
# Run with verbose logging
python -c "
import logging
logging.basicConfig(level=logging.DEBUG)
exec(open('matrix.py').read())
"
```

## 📋 Requirements

- **Python 3.7+**
- **FFmpeg with VMAF support**
- **Required packages**: numpy, pandas, opencv-python, ffmpeg-python

## 🤝 Contributing

1. Fork the repository
2. Create algorithm implementations following the standard interface
3. Add comprehensive tests for new features
4. Submit pull requests with detailed descriptions

## 📄 License

This project is open source. See LICENSE file for details.

## 📞 Support

For issues and questions:
- Check the troubleshooting section
- Review algorithm implementation examples
- Ensure all dependencies are properly installed
- Verify FFmpeg VMAF support: `ffmpeg -filters | grep vmaf`

---

**Happy compression testing! 🎬✨**
