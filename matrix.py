#!/usr/bin/env python3
"""
Video Compression Algorithm Testing Matrix
Evaluates multiple compression algorithms on multiple videos using VMAF and compression ratios.
"""

import os
import sys
import json
import subprocess
import configparser
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Dict, List, Tuple, Any
import logging
import time

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class VideoCompressionMatrix:
    def __init__(self, config_file: str = "config.ini"):
        """Initialize the video compression matrix evaluator."""
        self.config = self._load_config(config_file)
        self.supported_formats = [fmt.strip().lower() for fmt in self.config.get('SUPPORTED_FORMATS', 'mov,mp4,webm,mvi,mkv,avi').split(',')]
        self.videos = []
        self.algorithms = []
        self.vmaf_matrix = None
        self.compression_matrix = None

    def _load_config(self, config_file: str) -> Dict[str, Any]:
        """Load configuration from file."""
        if not os.path.exists(config_file):
            raise FileNotFoundError(f"Configuration file {config_file} not found!")

        config_dict = {}

        # Parse as simple key=value format
        with open(config_file, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    config_dict[key.strip().upper()] = value.strip()

        return config_dict

    def discover_videos(self) -> List[str]:
        """Discover all supported video files in the video directory."""
        video_path = Path(self.config.get('VIDEO_PATH', './test_videos'))
        if not video_path.exists():
            logger.warning(f"Video directory {video_path} does not exist!")
            return []

        videos = []
        for ext in self.supported_formats:
            pattern = f"*.{ext}"
            videos.extend(video_path.glob(pattern))

        # Also check subdirectories
        for subdir in video_path.iterdir():
            if subdir.is_dir():
                for ext in self.supported_formats:
                    pattern = f"*.{ext}"
                    videos.extend(subdir.glob(pattern))

        self.videos = [str(video) for video in videos]

        # Limit based on config if specified
        no_of_videos = int(self.config.get('NO_OF_VIDEOS', -1))
        if no_of_videos > 0:
            self.videos = self.videos[:no_of_videos]

        logger.info(f"Discovered {len(self.videos)} videos")
        return self.videos

    def discover_algorithms(self) -> List[str]:
        """Discover all algorithm implementations in the algorithm directory."""
        algo_path = Path(self.config.get('ALGO_PATH', './algorithms'))
        if not algo_path.exists():
            logger.warning(f"Algorithm directory {algo_path} does not exist!")
            return []

        algorithms = []
        for item in algo_path.iterdir():
            if item.is_dir():
                # Check if algorithm directory has required structure
                if self._validate_algorithm_structure(item):
                    algorithms.append(str(item))

        self.algorithms = algorithms

        # Limit based on config if specified
        no_of_algorithms = int(self.config.get('NO_OF_ALGORITHMS', -1))
        if no_of_algorithms > 0:
            self.algorithms = self.algorithms[:no_of_algorithms]

        logger.info(f"Discovered {len(self.algorithms)} algorithms")
        return self.algorithms

    def _validate_algorithm_structure(self, algo_dir: Path) -> bool:
        """Validate that an algorithm directory has the required structure."""
        required_files = ['compress.py', 'config.json']

        for required_file in required_files:
            if not (algo_dir / required_file).exists():
                logger.warning(f"Algorithm {algo_dir.name} missing {required_file}")
                return False
        return True

    def run_algorithm(self, algorithm_path: str, input_video: str, output_video: str) -> bool:
        """Run a specific algorithm on a video."""
        try:
            # Create output directory if it doesn't exist
            Path(output_video).parent.mkdir(parents=True, exist_ok=True)

            # Run the algorithm's compress.py script
            cmd = [
                sys.executable,
                os.path.join(algorithm_path, 'compress.py'),
                '--input', input_video,
                '--output', output_video
            ]

            start_time = time.time()
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)  # 10 minute timeout
            end_time = time.time()

            if result.returncode == 0:
                logger.info(f"Successfully compressed {Path(input_video).name} using {Path(algorithm_path).name} in {end_time-start_time:.2f}s")
                return True
            else:
                logger.error(f"Algorithm {Path(algorithm_path).name} failed: {result.stderr}")
                return False

        except subprocess.TimeoutExpired:
            logger.error(f"Algorithm {Path(algorithm_path).name} timed out")
            return False
        except Exception as e:
            logger.error(f"Error running algorithm {Path(algorithm_path).name}: {e}")
            return False



    def calculate_vmaf(self, original_video: str, compressed_video: str) -> float:
        """
        Robust VMAF runner that tries multiple ways to pass a JSON log path to libvmaf on Windows.
        Paste-replace only this method. Relies on:
        - self._parse_vmaf_from_json(json_path)
        - self._parse_vmaf_from_output(stderr)
        - self._parse_vmaf_from_csv_output(stderr)
        """
        import subprocess, tempfile, os, time
        from pathlib import Path

        logger.info("Starting VMAF calculation (robust Windows-aware)")

        # resolve input paths
        original = str(Path(original_video).resolve())
        compressed = str(Path(compressed_video).resolve())

        # where to create temp log (create in cwd so we can use a relative path without drive letter)
        tmp_dir = Path.cwd()
        tf = tempfile.NamedTemporaryFile(prefix="vmaf_", suffix=".json", dir=str(tmp_dir), delete=False)
        tf.close()
        temp_log = Path(tf.name)  # absolute path
        rel_log = os.path.relpath(temp_log)  # relative path (no drive letter)
        rel_log_unix = rel_log.replace("\\", "/")  # forward slashes
        abs_log_unix = str(temp_log).replace("\\", "/")
        abs_log_escaped_colon = abs_log_unix.replace(":", "\\:")  # C\:/...
        safe_variants = [
            ("relative_no_quote", rel_log_unix),                              # vmaf_temp.json or subdir/vmaf_....json
            ("relative_single_quote", f"'{rel_log_unix}'"),                    # 'rel/path'
            ("absolute_escape_colon_no_quote", abs_log_escaped_colon),         # C\:/path...
            ("absolute_single_quote_escaped_colon", f"'{abs_log_escaped_colon}'"),  # 'C\:/path...'
        ]

        # try filters (prefer libvmaf)
        filter_name = "libvmaf"

        # helper to run ffmpeg for a given logpath variant and try parse
        def _try_with_logpath(logpath_str: str) -> float:
            # build lavfi argument
            lavfi = f"[0:v][1:v]{filter_name}=log_fmt=json:log_path={logpath_str}"
            cmd = [
                "ffmpeg",
                "-hide_banner",
                "-y",
                "-i", original,
                "-i", compressed,
                "-lavfi", lavfi,
                "-f", "null", "-"
            ]
            logger.info("[VMAF] Attempt (%s): ffmpeg -lavfi %s", logpath_str, lavfi)
            try:
                proc = subprocess.run(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=600,
                    check=False
                )
            except FileNotFoundError:
                logger.error("[VMAF] ffmpeg not found in PATH.")
                return 0.0
            except subprocess.TimeoutExpired:
                logger.error("[VMAF] ffmpeg timed out for attempt %s", logpath_str)
                return 0.0
            except Exception as e:
                logger.exception("[VMAF] Unexpected error running ffmpeg: %s", e)
                return 0.0

            logger.debug("[VMAF] ffmpeg exitcode=%s", proc.returncode)
            logger.debug("[VMAF] ffmpeg stderr (first 500):\n%s", (proc.stderr or "")[:500])
            logger.debug("[VMAF] ffmpeg stdout (first 200):\n%s", (proc.stdout or "")[:200])

            # If ffmpeg produced the JSON file, try parsing it (give Windows a moment to flush)
            try:
                # prefer the actual absolute file path for reading regardless of what we passed to ffmpeg
                if temp_log.exists():
                    time.sleep(0.15)
                    size = temp_log.stat().st_size
                    logger.debug("[VMAF] temp log exists size=%d bytes", size)
                    if size > 10:
                        try:
                            score = self._parse_vmaf_from_json(str(temp_log))
                            if score > 0:
                                logger.info("[VMAF] Parsed JSON VMAF: %.3f (using %s)", score, logpath_str)
                                return score
                        except Exception as e:
                            logger.debug("[VMAF] JSON parse error: %s", e)
                    else:
                        logger.debug("[VMAF] temp log present but empty or tiny (size=%d)", size)
            except Exception as e:
                logger.debug("[VMAF] error checking temp log: %s", e)

            # fallback: parse stderr (CSV / textual)
            try:
                score_csv = self._parse_vmaf_from_csv_output(proc.stderr or "")
                if score_csv > 0:
                    logger.info("[VMAF] Parsed VMAF from CSV stderr: %.3f", score_csv)
                    return score_csv
            except Exception as e:
                logger.debug("[VMAF] CSV parse error: %s", e)

            try:
                score_txt = self._parse_vmaf_from_output(proc.stderr or "")
                if score_txt > 0:
                    logger.info("[VMAF] Parsed VMAF from stderr text: %.3f", score_txt)
                    return score_txt
            except Exception as e:
                logger.debug("[VMAF] stderr text parse error: %s", e)

            return 0.0

        try:
            # Attempt variants in order (relative path first avoids drive-colon problems)
            for name, variant in safe_variants:
                logger.debug("[VMAF] Trying variant: %s -> %s", name, variant)
                score = _try_with_logpath(variant)
                if score > 0:
                    try:
                        temp_log.unlink()
                    except Exception:
                        pass
                    return score

            # If none of the logpath variants worked: try in-memory csv/stderr without json log
            logger.info("[VMAF] Falling back to in-memory libvmaf (no log file).")
            lavfi = f"[0:v][1:v]{filter_name}=log_fmt=csv"
            cmd = [
                "ffmpeg",
                "-hide_banner",
                "-y",
                "-i", original,
                "-i", compressed,
                "-lavfi", lavfi,
                "-f", "null", "-"
            ]
            proc = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=600,
                check=False
            )
            logger.debug("[VMAF] In-memory ffmpeg stderr (first 500):\n%s", (proc.stderr or "")[:500])
            score = self._parse_vmaf_from_csv_output(proc.stderr or "")
            if score > 0:
                logger.info("[VMAF] Parsed VMAF from in-memory CSV: %.3f", score)
                return score
            score = self._parse_vmaf_from_output(proc.stderr or "")
            if score > 0:
                logger.info("[VMAF] Parsed VMAF from in-memory stderr: %.3f", score)
                return score

            # Nothing worked
            logger.error("All VMAF calculation methods failed. Last ffmpeg stderr (first 500):\n%s",
                        (proc.stderr or "")[:500])
            return 0.0

        finally:
            # cleanup temp file
            try:
                if temp_log.exists():
                    temp_log.unlink()
            except Exception:
                pass

    def _parse_vmaf_from_json(self, json_file: str) -> float:
        """Parse VMAF score from JSON log file."""
        try:
            import json
            with open(json_file, 'r', encoding='utf-8') as f:
                vmaf_data = json.load(f)
            
            # Extract average VMAF score from frames
            frames = vmaf_data.get('frames', [])
            if frames:
                vmaf_scores = []
                for frame in frames:
                    metrics = frame.get('metrics', {})
                    if 'vmaf' in metrics:
                        vmaf_scores.append(float(metrics['vmaf']))
                
                if vmaf_scores:
                    avg_vmaf = sum(vmaf_scores) / len(vmaf_scores)
                    return avg_vmaf
            
            # Alternative: check if there's a pooled score
            pooled = vmaf_data.get('pooled_metrics', {})
            if 'vmaf' in pooled:
                return float(pooled['vmaf']['mean'])
                
        except Exception as e:
            logger.debug(f"Error parsing VMAF JSON: {e}")
        
        return 0.0

    def _parse_vmaf_from_csv_output(self, stderr_output: str) -> float:
        """Parse VMAF score from CSV format output in stderr."""
        try:
            import re
            lines = stderr_output.split('\n')
            vmaf_scores = []
            
            for line in lines:
                # Look for CSV-like VMAF data
                if ',' in line and 'vmaf' in line.lower():
                    # Try to extract VMAF values from CSV line
                    parts = line.split(',')
                    for part in parts:
                        if 'vmaf' in part.lower():
                            # Extract number after vmaf
                            match = re.search(r'vmaf[:\s=]+([0-9]+\.?[0-9]*)', part.lower())
                            if match:
                                score = float(match.group(1))
                                if 0 <= score <= 100:
                                    vmaf_scores.append(score)
                
                # Also look for direct VMAF values in CSV format
                if re.match(r'^[0-9]+,.*,[0-9]+\.[0-9]+', line):
                    parts = line.split(',')
                    for part in parts:
                        try:
                            val = float(part.strip())
                            if 20 <= val <= 100:  # Reasonable VMAF range
                                vmaf_scores.append(val)
                        except:
                            continue
            
            if vmaf_scores:
                return sum(vmaf_scores) / len(vmaf_scores)
                
        except Exception as e:
            logger.debug(f"Error parsing CSV VMAF: {e}")
        
        return 0.0

    def _parse_vmaf_from_output(self, stderr_output: str) -> float:
        """Parse VMAF score from general stderr text output."""
        try:
            import re
            lines = stderr_output.split('\n')
            vmaf_scores = []
            
            for line in lines:
                # Look for various VMAF output patterns
                patterns = [
                    r'vmaf[:\s=]+([0-9]+\.?[0-9]*)',
                    r'mean[:\s=]+([0-9]+\.?[0-9]*)',
                    r'average[:\s=]+([0-9]+\.?[0-9]*)',
                    r'n:[0-9]+.*vmaf:([0-9]+\.?[0-9]*)',
                    r'VMAF score[:\s=]+([0-9]+\.?[0-9]*)'
                ]
                
                for pattern in patterns:
                    matches = re.findall(pattern, line.lower())
                    for match in matches:
                        try:
                            score = float(match)
                            if 0 <= score <= 100:
                                vmaf_scores.append(score)
                        except:
                            continue
                
                # Look for frame-by-frame VMAF scores
                if 'n:' in line and 'vmaf:' in line.lower():
                    try:
                        vmaf_part = line.lower().split('vmaf:')[1].split()[0]
                        score = float(vmaf_part.strip(','))
                        if 0 <= score <= 100:
                            vmaf_scores.append(score)
                    except:
                        continue
            
            if vmaf_scores:
                # Return average of all found scores
                return sum(vmaf_scores) / len(vmaf_scores)
            
        except Exception as e:
            logger.debug(f"Error parsing stderr VMAF: {e}")
        
        return 0.0

    def _parse_vmaf_from_json(self, json_file: str) -> float:
        """Parse VMAF score from JSON log file."""
        try:
            with open(json_file, 'r') as f:
                vmaf_data = json.load(f)

            # Extract average VMAF score
            frames = vmaf_data.get('frames', [])
            if frames:
                vmaf_scores = []
                for frame in frames:
                    metrics = frame.get('metrics', {})
                    if 'vmaf' in metrics:
                        vmaf_scores.append(float(metrics['vmaf']))

                if vmaf_scores:
                    return sum(vmaf_scores) / len(vmaf_scores)

        except Exception as e:
            logger.error(f"Error parsing VMAF JSON: {e}")

        return 0.0

    def _parse_vmaf_from_csv_output(self, stderr_output: str) -> float:
        """Parse VMAF score from CSV format output."""
        try:
            lines = stderr_output.split('\n')
            vmaf_scores = []

            for line in lines:
                # Look for CSV-like VMAF data
                if ',' in line and 'vmaf' in line.lower():
                    parts = line.split(',')
                    for part in parts:
                        try:
                            if 'vmaf' in part.lower():
                                # Extract number after vmaf
                                score_part = part.lower().split('vmaf')[1]
                                import re
                                numbers = re.findall(r'[0-9]+\.?[0-9]*', score_part)
                                if numbers:
                                    score = float(numbers[0])
                                    if 0 <= score <= 100:
                                        vmaf_scores.append(score)
                        except:
                            continue

            if vmaf_scores:
                return sum(vmaf_scores) / len(vmaf_scores)

        except Exception as e:
            logger.error(f"Error parsing CSV VMAF: {e}")

        return 0.0

    def calculate_compression_ratio(self, original_video: str, compressed_video: str) -> float:
        """Calculate compression ratio between original and compressed video."""
        try:
            if not os.path.exists(compressed_video):
                return 0.0

            original_size = os.path.getsize(original_video)
            compressed_size = os.path.getsize(compressed_video)

            if compressed_size == 0:
                return 0.0

            compression_ratio = original_size / compressed_size
            return compression_ratio

        except Exception as e:
            logger.error(f"Error calculating compression ratio: {e}")
            return 0.0

    def generate_matrices(self) -> Tuple[np.ndarray, np.ndarray]:
        """Generate VMAF and compression ratio matrices for all algorithms and videos."""
        num_videos = len(self.videos)
        num_algorithms = len(self.algorithms)

        if num_videos == 0 or num_algorithms == 0:
            logger.error("No videos or algorithms found!")
            return None, None

        vmaf_matrix = np.zeros((num_videos, num_algorithms))
        compression_matrix = np.zeros((num_videos, num_algorithms))

        output_base_path = Path(self.config.get('OUTPUT_VIDEO_PATH', './output_videos'))

        for i, video in enumerate(self.videos):
            video_name = Path(video).stem
            logger.info(f"Processing video {i+1}/{num_videos}: {video_name}")

            for j, algorithm in enumerate(self.algorithms):
                algo_name = Path(algorithm).name
                logger.info(f"  Running algorithm {j+1}/{num_algorithms}: {algo_name}")

                    # Generate output path
                if 'vp9' in algo_name.lower():
                    output_video = output_base_path / algo_name / f"{video_name}_compressed.webm"
                else:
                    output_video = output_base_path / algo_name / f"{video_name}_compressed.mp4"

                # Run compression algorithm
                if self.run_algorithm(algorithm, video, str(output_video)):
                    # Calculate VMAF score
                    vmaf_score = self.calculate_vmaf(video, str(output_video))
                    vmaf_matrix[i, j] = vmaf_score

                    # Calculate compression ratio
                    comp_ratio = self.calculate_compression_ratio(video, str(output_video))
                    compression_matrix[i, j] = comp_ratio

                    logger.info(f"    VMAF: {vmaf_score:.2f}, Compression: {comp_ratio:.2f}x")
                else:
                    logger.warning(f"    Failed to compress with {algo_name}")
                    vmaf_matrix[i, j] = 0.0
                    compression_matrix[i, j] = 0.0

        self.vmaf_matrix = vmaf_matrix
        self.compression_matrix = compression_matrix

        return vmaf_matrix, compression_matrix

    def save_results(self, output_dir: str = "./results"):
        """Save matrices and results to files."""
        Path(output_dir).mkdir(parents=True, exist_ok=True)

        video_names = [Path(v).stem for v in self.videos]
        algo_names = [Path(a).name for a in self.algorithms]

        # Save VMAF matrix as CSV
        vmaf_df = pd.DataFrame(self.vmaf_matrix, index=video_names, columns=algo_names)
        vmaf_df.to_csv(os.path.join(output_dir, 'vmaf_matrix.csv'))

        # Save compression matrix as CSV
        comp_df = pd.DataFrame(self.compression_matrix, index=video_names, columns=algo_names)
        comp_df.to_csv(os.path.join(output_dir, 'compression_matrix.csv'))

        # Save summary statistics
        summary = {
            'total_videos': len(self.videos),
            'total_algorithms': len(self.algorithms),
            'video_names': video_names,
            'algorithm_names': algo_names,
            'average_vmaf_per_algorithm': {
                algo: float(score) for algo, score in zip(algo_names, self.vmaf_matrix.mean(axis=0))
            },
            'average_compression_per_algorithm': {
                algo: float(ratio) for algo, ratio in zip(algo_names, self.compression_matrix.mean(axis=0))
            },
            'note': 'VMAF scores are estimated based on compression ratios - not actual VMAF calculations'
        }

        with open(os.path.join(output_dir, 'summary.json'), 'w') as f:
            json.dump(summary, f, indent=2)

        logger.info(f"Results saved to {output_dir}")

    def print_stats(self):
        """Print discovery and processing statistics."""
        print("\n" + "="*70)
        print("[MATRIX] VIDEO COMPRESSION ALGORITHM TESTING MATRIX")
        print("="*70)
        print(f"[CONFIG] Configuration loaded successfully!")
        print(f"[STATS] Videos discovered: {len(self.videos)}")
        print(f"[STATS] Algorithms discovered: {len(self.algorithms)}")
        print()

        if self.videos:
            print("[VIDEOS] DISCOVERED VIDEOS:")
            for i, video in enumerate(self.videos, 1):
                try:
                    size_mb = os.path.getsize(video) / (1024 * 1024)
                    print(f"  {i:2d}. {Path(video).name} ({size_mb:.1f} MB)")
                except:
                    print(f"  {i:2d}. {Path(video).name}")

        if self.algorithms:
            print(f"\n[ALGOS] DISCOVERED ALGORITHMS:")
            for i, algo in enumerate(self.algorithms, 1):
                try:
                    config_path = Path(algo) / 'config.json'
                    if config_path.exists():
                        with open(config_path, 'r') as f:
                            algo_config = json.load(f)
                        name = algo_config.get('algorithm_name', Path(algo).name)
                        print(f"  {i:2d}. {name} ({Path(algo).name})")
                    else:
                        print(f"  {i:2d}. {Path(algo).name}")
                except:
                    print(f"  {i:2d}. {Path(algo).name}")

        print(f"\n[FORMAT] Supported formats: {', '.join(self.supported_formats)}")
        print(f"[OUTPUT] Output directory: {self.config.get('OUTPUT_VIDEO_PATH', './output_videos')}")
        print(f"[NOTE] VMAF scores will be estimated based on compression ratios")
        print("="*70)

    def run(self):
        """Main execution function."""
        logger.info("Starting Video Compression Matrix Generation")

        # Discover videos and algorithms
        self.discover_videos()
        self.discover_algorithms()

        # Print statistics
        self.print_stats()

        if not self.videos:
            logger.error("[ERROR] No videos found! Please check your VIDEO_PATH configuration.")
            return

        if not self.algorithms:
            logger.error("[ERROR] No algorithms found! Please check your ALGO_PATH configuration.")
            return

        # Generate matrices
        logger.info("[PROCESSING] Generating VMAF and compression matrices...")
        vmaf_matrix, compression_matrix = self.generate_matrices()

        if vmaf_matrix is not None and compression_matrix is not None:
            # Save results
            self.save_results()

            # Print final summary
            print(f"\n[SUCCESS] MATRIX GENERATION COMPLETE!")
            print(f"[RESULTS] Results saved to ./results/")
            print("\n[SUMMARY] SUMMARY STATISTICS:")

            algo_names = [Path(a).name for a in self.algorithms]
            avg_vmaf = np.mean(vmaf_matrix, axis=0)
            avg_compression = np.mean(compression_matrix, axis=0)

            for i, algo in enumerate(algo_names):
                print(f"  {algo}: Estimated VMAF={avg_vmaf[i]:.2f}, Compression={avg_compression[i]:.2f}x")

        else:
            logger.error("[ERROR] Failed to generate matrices!")


def main():
    """Main entry point."""
    config_file = "config.ini" if len(sys.argv) < 2 else sys.argv[1]

    try:
        matrix = VideoCompressionMatrix(config_file)
        matrix.run()
    except KeyboardInterrupt:
        logger.info("Process interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
