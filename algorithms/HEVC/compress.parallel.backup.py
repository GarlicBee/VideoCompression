#!/usr/bin/env python3
"""
# H.265/HEVC Video Compression Algorithm with Automatic CRF Optimization
# Automatically optimizes CRF to maximize SF score when called
# SF = w_c*(1-c^1.5) + w_vmaf*(VMAF-VMAF_threshold)/(100-VMAF_threshold)
# """

import argparse
import json
import os
import subprocess
import sys
import time
import shutil
import tempfile
from pathlib import Path
from typing import Dict, Any, Tuple, List
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, as_completed

class H265Compressor:
    def __init__(self, config_file: str = "config.json"):
        """Initialize H.265 compressor with configuration."""
        self.config = self._load_config(config_file)
        self.start_time = None

        # Load optimization parameters from config
        opt_params = self.config.get('optimization_params', {})
        self.vmaf_threshold = opt_params.get('vmaf_threshold', 85)
        self.w_c = opt_params.get('w_c', 0.8)
        self.w_vmaf = opt_params.get('w_vmaf', 0.2)
        self.crf_min = opt_params.get('crf_min', 28)
        self.crf_max = opt_params.get('crf_max', 34)
        self.crf_step = opt_params.get('crf_step', 2)

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
            },
            "optimization_params": {
                "vmaf_threshold": 85,
                "w_c": 0.8,
                "w_vmaf": 0.2,
                "crf_min": 28,
                "crf_max": 34,
                "crf_step": 2
            }
        }

        if config_path.exists():
            try:
                with open(config_path, 'r') as f:
                    loaded_config = json.load(f)
                # Merge with defaults (including nested dicts)
                for key, value in loaded_config.items():
                    if isinstance(value, dict) and key in default_config:
                        default_config[key].update(value)
                    else:
                        default_config[key] = value
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


# ============================================================================
# CRF OPTIMIZATION FUNCTIONS
# ============================================================================

def compute_vmaf(original: str, compressed: str) -> float:
    """
    Compute VMAF score between original and compressed video using ffmpeg.

    Args:
        original: Path to original video
        compressed: Path to compressed video

    Returns:
        VMAF score (0-100), or None if computation fails
    """
    try:
        # Create temporary file for VMAF log
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as tmp:
            vmaf_log_path = tmp.name

        # Use absolute paths
        original = os.path.abspath(original)
        compressed = os.path.abspath(compressed)

        # Build VMAF command
        vmaf_cmd = [
            'ffmpeg',
            '-i', original,
            '-i', compressed,
            '-lavfi',
            f'[0:v]scale=960:540:force_original_aspect_ratio=decrease[ref];'
            f'[1:v]scale=960:540:force_original_aspect_ratio=decrease[dist];'
            f'[ref][dist]libvmaf=log_path={vmaf_log_path}:log_fmt=json',
            '-f', 'null',
            '-'
        ]

        # Run VMAF calculation
        result = subprocess.run(
            vmaf_cmd,
            capture_output=True,
            text=True,
            timeout=300  # 5 minute timeout
        )

        # Parse VMAF score from log file
        if os.path.exists(vmaf_log_path):
            try:
                with open(vmaf_log_path, 'r') as f:
                    vmaf_data = json.load(f)
                    # Extract pooled VMAF score
                    vmaf_score = vmaf_data.get('pooled_metrics', {}).get('vmaf', {}).get('mean')
                    if vmaf_score is not None:
                        return float(vmaf_score)
            finally:
                # Clean up temp file
                try:
                    os.unlink(vmaf_log_path)
                except:
                    pass

        # Fallback: try parsing from stderr
        for line in result.stderr.split('\n'):
            if 'VMAF score' in line:
                try:
                    vmaf_score = float(line.split(':')[-1].strip())
                    return vmaf_score
                except (ValueError, IndexError):
                    continue

        print(f"[WARNING] Could not extract VMAF score")
        return None

    except subprocess.TimeoutExpired:
        print(f"[ERROR] VMAF computation timed out")
        return None
    except Exception as e:
        print(f"[ERROR] VMAF computation failed: {e}")
        return None


def calculate_sf(c: float, vmaf: float, w_c: float, w_vmaf: float, vmaf_threshold: float) -> float:
    """
    Calculate SF (Score Function) for optimization.

    SF = w_c*(1-c^1.5) + w_vmaf*(VMAF-VMAF_threshold)/(100-VMAF_threshold)

    Args:
        c: Compression ratio (compressed_size / original_size)
        vmaf: VMAF score (0-100)
        w_c: Weight for compression component
        w_vmaf: Weight for VMAF component
        vmaf_threshold: VMAF threshold value

    Returns:
        SF score
    """
    if vmaf is None:
        return -float('inf')  # Invalid score for failed VMAF

    sf = w_c * (1 - c**1.5) + w_vmaf * ((vmaf - vmaf_threshold) / (100 - vmaf_threshold))
    #print(f"[CRF {crf}] -> VMAF={vmaf:.2f}, c={c:.4f}, SF={sf:.4f}")
    return sf


def compress_with_crf(input_video: str, crf: int, compressor: H265Compressor, 
                      output_base: str, orig_size: int) -> Dict[str, Any]:
    """
    Compress video with a specific CRF value.

    Args:
        input_video: Path to input video
        crf: CRF value to use
        compressor: H265Compressor instance
        output_base: Base path for output (will append _crfXX)
        orig_size: Original video size in bytes

    Returns:
        Dictionary with crf, output path, and compression info
    """
    print(f"\n[CRF {crf}] Starting compression...")

    # Create unique output path for this CRF
    output_path = Path(output_base)
    temp_output = str(output_path.parent / f"{output_path.stem}_crf{crf}{output_path.suffix}")

    try:
        # Set CRF in config
        compressor.config['parameters']['crf'] = crf

        # Build and run compression
        cmd = compressor._build_ffmpeg_command(input_video, temp_output)

        start_time = time.time()
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600  # 10 minute timeout
        )
        compression_time = time.time() - start_time

        if result.returncode != 0:
            print(f"[CRF {crf}] Compression failed")
            return {
                'crf': crf,
                'output': temp_output,
                'success': False,
                'compression_time': compression_time
            }

        # Get compressed file size
        output_size = os.path.getsize(temp_output)
        c = output_size / orig_size

        print(f"[CRF {crf}] Compression completed in {compression_time:.1f}s, c={c:.4f}")

        return {
            'crf': crf,
            'output': temp_output,
            'success': True,
            'compression_time': compression_time,
            'c': c,
            'size': output_size
        }

    except subprocess.TimeoutExpired:
        print(f"[CRF {crf}] Compression timed out")
        return {
            'crf': crf,
            'output': temp_output,
            'success': False,
            'compression_time': 0
        }
    except Exception as e:
        print(f"[CRF {crf}] Error: {e}")
        return {
            'crf': crf,
            'output': temp_output,
            'success': False,
            'compression_time': 0
        }


def compute_vmaf_for_result(input_video: str, result: Dict[str, Any], 
                            w_c: float, w_vmaf: float, vmaf_threshold: float) -> Dict[str, Any]:
    """
    Compute VMAF and SF for a compressed video result.

    Args:
        input_video: Path to original video
        result: Dictionary with compression result info
        w_c: Weight for compression component
        w_vmaf: Weight for VMAF component
        vmaf_threshold: VMAF threshold value

    Returns:
        Updated result dictionary with VMAF and SF
    """
    if not result.get('success', False):
        result['vmaf'] = None
        result['sf'] = -float('inf')
        return result

    crf = result['crf']
    compressed_video = result['output']
    c = result['c']

    print(f"[CRF {crf}] Computing VMAF...")
    vmaf = compute_vmaf(input_video, compressed_video)

    if vmaf is None:
        print(f"[CRF {crf}] VMAF computation failed")
        sf = -float('inf')
    else:
        sf = calculate_sf(c, vmaf, w_c, w_vmaf, vmaf_threshold)
        print(f"[CRF {crf}] VMAF={vmaf:.2f}, SF={sf:.4f}")

    result['vmaf'] = vmaf
    result['sf'] = sf
    return result


def optimize_crf_parallel(input_video: str, output_video: str, 
                          compressor: H265Compressor) -> Dict[str, Any]:
    """
    Optimize CRF value using parallel compression and VMAF evaluation to maximize SF.

    Phase 1: Compress all CRF values in parallel
    Phase 2: Compute VMAF for all compressed videos in parallel

    Args:
        input_video: Path to input video
        output_video: Path for final output video
        compressor: H265Compressor instance

    Returns:
        Dictionary with best CRF and quality metrics
    """
    print(f"\n{'='*70}")
    print(f"[OPTIMIZE] Starting CRF optimization")
    print(f"[OPTIMIZE] CRF range: {compressor.crf_min}-{compressor.crf_max}, step={compressor.crf_step}")
    print(f"[OPTIMIZE] SF params: w_c={compressor.w_c}, w_vmaf={compressor.w_vmaf}, VMAF_threshold={compressor.vmaf_threshold}")
    print(f"{'='*70}")

    # Get original size
    orig_size = os.path.getsize(input_video)
    print(f"[OPTIMIZE] Original size: {orig_size / (1024*1024):.2f} MB")

    # CRF range to evaluate
    crf_range = range(compressor.crf_min, compressor.crf_max + 1, compressor.crf_step)
    print(f"[OPTIMIZE] Testing CRF values: {list(crf_range)}")

    # PHASE 1: Compress all CRF values in parallel
    print(f"\n[PHASE 1] Compressing videos with all CRF values in parallel...")
    compression_results = []
    with ThreadPoolExecutor(max_workers=len(crf_range)) as executor:
        futures = []
        for crf in crf_range:
            future = executor.submit(
                compress_with_crf,
                input_video,
                crf,
                compressor,
                output_video,
                orig_size
            )
            futures.append(future)

        # Collect compression results
        for future in as_completed(futures):
            try:
                result = future.result()
                compression_results.append(result)
            except Exception as e:
                print(f"[ERROR] Compression future failed: {e}")

    # Filter successful compressions
    valid_compressions = [r for r in compression_results if r.get('success', False)]

    if not valid_compressions:
        print(f"[ERROR] No successful compressions!")
        return None

    print(f"[PHASE 1] Completed {len(valid_compressions)}/{len(crf_range)} compressions successfully")

    # PHASE 2: Compute VMAF for all compressed videos in parallel
    print(f"\n[PHASE 2] Computing VMAF for all compressed videos in parallel...")
    final_results = []
    with ThreadPoolExecutor(max_workers=len(valid_compressions)) as executor:
        futures = []
        for result in valid_compressions:
            future = executor.submit(
                compute_vmaf_for_result,
                input_video,
                result,
                compressor.w_c,
                compressor.w_vmaf,
                compressor.vmaf_threshold
            )
            futures.append(future)

        # Collect VMAF results
        for future in as_completed(futures):
            try:
                result = future.result()
                final_results.append(result)
            except Exception as e:
                print(f"[ERROR] VMAF future failed: {e}")

    # Filter results with valid VMAF
    valid_results = [r for r in final_results if r.get('vmaf') is not None]

    if not valid_results:
        print(f"[ERROR] No valid VMAF scores computed!")
        return None

    # Find best SF
    best = max(valid_results, key=lambda r: r.get('sf', -float('inf')))

    print(f"\n{'='*70}")
    print(f"[OPTIMIZE] Results Summary:")
    print(f"{'='*70}")

    # Sort results by CRF for display
    for result in sorted(valid_results, key=lambda r: r['crf']):
        crf = result['crf']
        sf = result.get('sf', -float('inf'))
        vmaf = result.get('vmaf', 0)
        c = result.get('c', 1)
        marker = " <- BEST" if result == best else ""
        print(f"  CRF {crf}: SF={sf:.4f}, VMAF={vmaf:.2f}, c={c:.4f}{marker}")

    print(f"\n[OPTIMIZE] Best CRF: {best['crf']}")
    print(f"[OPTIMIZE] Best SF: {best['sf']:.4f}")
    print(f"[OPTIMIZE] VMAF: {best.get('vmaf', 0):.2f}")
    print(f"[OPTIMIZE] Compression ratio: {best.get('c', 1):.4f}")

    # Move best result to final output
    try:
        if os.path.exists(output_video):
            os.remove(output_video)
        shutil.move(best['output'], output_video)
        print(f"[OPTIMIZE] Saved best result to: {output_video}")
    except Exception as e:
        print(f"[ERROR] Failed to move best result: {e}")

    # Clean up other temporary files
    for result in final_results:
        if result != best and os.path.exists(result.get('output', '')):
            try:
                os.remove(result['output'])
            except:
                pass

    return best


def main():
    """
    Main entry point for H.265 compression with automatic CRF optimization.
    Always runs optimization when called from matrix.py.
    """
    parser = argparse.ArgumentParser(
        description='H.265/HEVC Video Compression with Automatic CRF Optimization'
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

    # Initialize compressor
    try:
        compressor = H265Compressor(args.config)

        # Always run CRF optimization
        result = optimize_crf_parallel(args.input, args.output, compressor)
        success = result is not None

        sys.exit(0 if success else 1)

    except Exception as e:
        print(f"[ERROR] Failed to initialize compressor: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
