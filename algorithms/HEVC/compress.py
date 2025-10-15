#!/usr/bin/env python3
"""
H.265/HEVC Video Compression Algorithm
Advanced video compression using H.265 (HEVC) codec with optimized settings
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, Any

class H265Compressor:
    def __init__(self, config_file: str = "config.json"):
        """Initialize H.265 compressor with configuration."""
        self.config = self._load_config(config_file)
        self.start_time = None

    def _load_config(self, config_file: str) -> Dict[str, Any]:
        """Load algorithm configuration from JSON file."""
        config_path = Path(__file__).parent / config_file

        # Default configuration if file doesn't exist
        default_config = {
            "algorithm_name": "H.265 High Efficiency",
            "parameters": {
                "preset": "medium",
                "crf": 28,
                "profile": "main",
                "level": "4.1",
                "tune": "none",
                "threads": 0,
                "tile_columns": 2,
                "tile_rows": 1
            },
            "audio": {
                "codec": "aac",
                "bitrate": "128k",
                "sample_rate": 44100
            }
        }

        if config_path.exists():
            try:
                with open(config_path, 'r') as f:
                    loaded_config = json.load(f)
                # Merge with defaults
                default_config.update(loaded_config)
                return default_config
            except (json.JSONDecodeError, IOError) as e:
                print(f"Warning: Error loading config file: {e}")
                print("Using default configuration")

        return default_config

    def _validate_input(self, input_video: str) -> bool:
        """Validate input video file."""
        if not os.path.exists(input_video):
            print(f"Error: Input video file '{input_video}' does not exist!")
            return False

        # Check if file is readable
        try:
            with open(input_video, 'rb') as f:
                f.read(1024)  # Try to read first 1KB
        except IOError:
            print(f"Error: Cannot read input video file '{input_video}'!")
            return False

        return True

    def _get_video_info(self, video_path: str) -> Dict[str, Any]:
        """Get video information using ffprobe."""
        try:
            cmd = [
                'ffprobe',
                '-v', 'quiet',
                '-print_format', 'json',
                '-show_format',
                '-show_streams',
                video_path
            ]

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

            if result.returncode == 0:
                return json.loads(result.stdout)
            else:
                return {}

        except Exception:
            return {}

    def _build_ffmpeg_command(self, input_video: str, output_video: str) -> list:
        """Build FFmpeg command with H.265 parameters."""
        params = self.config.get('parameters', {})
        audio_params = self.config.get('audio', {})

        cmd = [
            'ffmpeg',
            '-y',  # Overwrite output file
            '-i', input_video,

            # Video codec settings
            '-c:v', 'libx265',
            '-preset', str(params.get('preset', 'medium')),
            '-crf', str(params.get('crf', 28)),
            '-profile:v', params.get('profile', 'main'),
            '-level', params.get('level', '4.1'),

            # Threading
            '-threads', str(params.get('threads', 0)),

            # H.265 specific optimizations
            '-x265-params', self._build_x265_params(params),

            # Audio settings
            '-c:a', audio_params.get('codec', 'aac'),
            '-b:a', audio_params.get('bitrate', '128k'),
            '-ar', str(audio_params.get('sample_rate', 44100)),

            # Output
            output_video
        ]

        # Add tuning if specified
        tune = params.get('tune', 'none')
        if tune and tune != 'none':
            cmd.extend(['-tune', tune])

        return cmd

    def _build_x265_params(self, params: Dict[str, Any]) -> str:
        """Build x265-specific parameter string."""
        x265_params = []

        # Tile settings for parallel processing
        tile_cols = params.get('tile_columns', 2)
        tile_rows = params.get('tile_rows', 1)
        if tile_cols > 0 and tile_rows > 0:
            x265_params.append(f"tiles={tile_cols}x{tile_rows}")

        # Rate control optimizations
        x265_params.extend([
            "rc-lookahead=25",
            "bframes=4",
            "b-adapt=2",
            "ref=3"
        ])

        # Quality optimizations
        x265_params.extend([
            "me=hex",
            "subme=2",
            "rd=2"
        ])

        return ":".join(x265_params)

    def compress(self, input_video: str, output_video: str) -> bool:
        """
        Main compression function using H.265/HEVC codec.

        Args:
            input_video (str): Path to input video file
            output_video (str): Path to output compressed video file

        Returns:
            bool: True if compression successful, False otherwise
        """
        self.start_time = time.time()

        print(f"[VIDEO] Starting H.265 compression...")
        print(f"[INPUT] {input_video}")
        print(f"[OUTPUT] {output_video}")

        # Validate input
        if not self._validate_input(input_video):
            return False

        # Create output directory
        try:
            Path(output_video).parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            print(f"[ERROR] Cannot create output directory: {e}")
            return False

        # Get input video information
        video_info = self._get_video_info(input_video)
        if video_info:
            format_info = video_info.get('format', {})
            duration = float(format_info.get('duration', 0))
            size_mb = int(format_info.get('size', 0)) / (1024 * 1024)
            print(f"[INFO] Input: {size_mb:.1f} MB, {duration:.1f}s")

        # Build and execute FFmpeg command
        cmd = self._build_ffmpeg_command(input_video, output_video)

        preset = self.config.get('parameters', {}).get('preset', 'medium')
        crf = self.config.get('parameters', {}).get('crf', 28)
        print(f"[CONFIG] Preset: {preset}, CRF: {crf}")

        try:
            # Run compression
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600  # 10 minute timeout
            )

            if result.returncode == 0:
                # Compression successful
                end_time = time.time()
                compression_time = end_time - self.start_time

                # Get output file info
                if os.path.exists(output_video):
                    output_size_mb = os.path.getsize(output_video) / (1024 * 1024)
                    if video_info:
                        input_size_mb = int(video_info.get('format', {}).get('size', 0)) / (1024 * 1024)
                        if input_size_mb > 0:
                            compression_ratio = input_size_mb / output_size_mb
                            print(f"[SUCCESS] Compressed: {compression_ratio:.1f}x reduction")
                            print(f"[SIZE] {input_size_mb:.1f} MB -> {output_size_mb:.1f} MB")
                            print(f"[TIME] {compression_time:.1f}s")
                            return True

                print(f"[SUCCESS] Compression completed in {compression_time:.1f}s")
                return True
            else:
                print(f"[ERROR] FFmpeg failed with return code: {result.returncode}")
                # Show only essential error info
                if result.stderr:
                    error_lines = result.stderr.split('\n')
                    for line in error_lines[-3:]:  # Last 3 lines
                        if line.strip() and 'error' in line.lower():
                            print(f"[ERROR] {line.strip()}")
                return False

        except subprocess.TimeoutExpired:
            print("[ERROR] Compression timed out!")
            return False
        except Exception as e:
            print(f"[ERROR] Compression failed: {e}")
            return False

def main():
    """Main entry point for H.265 compression algorithm."""
    # CORRECT argument parsing for compress.py
    parser = argparse.ArgumentParser(
        description='H.265/HEVC Video Compression Algorithm'
    )

    parser.add_argument(
        '--input', 
        required=True, 
        help='Input video file path'
    )
    parser.add_argument(
        '--output', 
        required=True, 
        help='Output compressed video file path'
    )
    parser.add_argument(
        '--config', 
        default='config.json', 
        help='Configuration file path (default: config.json)'
    )

    args = parser.parse_args()

    # Validate input file exists
    if not os.path.exists(args.input):
        print(f"[ERROR] Input file '{args.input}' does not exist!")
        sys.exit(1)

    # Initialize compressor and run compression
    try:
        compressor = H265Compressor(args.config)
        success = compressor.compress(args.input, args.output)
        sys.exit(0 if success else 1)

    except Exception as e:
        print(f"[ERROR] Failed to initialize compressor: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
