import os
import re
import ffmpeg
import subprocess
import json

class MultiviewerEngine:
    def __init__(self):
        # 3x3 Grid Matrix (Row-major)
        # [0, 1, 2]
        # [3, 4, 5]
        # [6, 7, 8]
        self.slot_patterns = {
            0: ["10_"],         # Row 1-1
            1: ["12_"],         # Row 1-2
            2: ["02_"],         # Row 1-3
            3: ["09_"],         # Row 2-1
            4: ["Top_", "13_"], # Row 2-2 (Center) - Priority: Top > 13
            5: ["03_"],         # Row 2-3
            6: ["08_"],         # Row 3-1
            7: ["06_"],         # Row 3-2
            8: ["04_"]          # Row 3-3
        }
        
    def scan_folder(self, folder_path):
        """
        Scans the folder and maps files to slots.
        Returns a dictionary {slot_index: file_path or None}
        """
        if not os.path.exists(folder_path):
            return {}

        files = os.listdir(folder_path)
        video_extensions = ('.mp4', '.mov', '.mkv', '.avi')
        video_files = [f for f in files if f.lower().endswith(video_extensions)]
        
        mapping = {i: None for i in range(9)}

        for slot, patterns in self.slot_patterns.items():
            for pattern in patterns:
                # Find first matching file with strict check
                # Pattern must be at START or preceded by _ to avoid substring match (e.g., 240913 matches 13_)
                match = next((f for f in video_files if f.startswith(pattern) or f"_{pattern}" in f), None)
                if match:
                    mapping[slot] = os.path.join(folder_path, match)
                    break # Stop if match found (priority Top > 13)
        
        return mapping

    def find_ffmpeg(self):
        """
        Attempts to find the FFmpeg binary in common locations.
        """
        import shutil
        
        # 1. Check if in PATH
        ffmpeg_bin = shutil.which("ffmpeg")
        if ffmpeg_bin:
            return ffmpeg_bin
            
        # 2. Check for static-ffmpeg
        try:
            import static_ffmpeg
            # This adds ffmpeg to the path for the current process
            static_ffmpeg.add_paths()
            ffmpeg_bin = shutil.which("ffmpeg")
            if ffmpeg_bin:
                return ffmpeg_bin
        except ImportError:
            pass
            
        # 3. Common Mac locations & specific static-ffmpeg paths
        common_paths = [
            "/Users/gimmyeongseob/Library/Python/3.9/lib/python/site-packages/static_ffmpeg/bin/darwin_arm64/ffmpeg",
            "/usr/local/bin/ffmpeg",
            "/opt/homebrew/bin/ffmpeg",
            "/usr/bin/ffmpeg"
        ]
        for path in common_paths:
            if os.path.exists(path):
                return path
                
        return "ffmpeg" # Fallback to default

    def build_command(self, file_mapping, output_path, overlay_text="", is_preview=False, codec_idx=0, lut_mapping=None):
        """
        Builds the FFmpeg command.
        """
        if lut_mapping is None:
            lut_mapping = {}
        
        ffmpeg_exe = self.find_ffmpeg()
        
        # Base input settings
        filter_complex = []
        valid_input_count = 0
        first_valid_input_path = None
        input_args = []
        
        # 1. Input Processing
        # Detect target FPS & Duration from first valid file for placeholders
        target_fps = 30.0
        target_duration = 0.0
        
        for i in range(9):
             path = file_mapping.get(i)
             if path:
                 target_fps = self.get_fps(path)
                 target_duration = self.get_duration(path)
                 break
                 
        for i in range(9):
            file_path = file_mapping.get(i)
            if file_path:
                input_args.extend(['-i', file_path])
                valid_input_count += 1
                if not first_valid_input_path:
                    first_valid_input_path = file_path
                
                # Check for LUT
                lut_filter = ""
                if i in lut_mapping and lut_mapping[i]:
                    lut_path = lut_mapping[i]
                    # Escape path for FFmpeg filter: replace \ with / and escape :
                    safe_lut_path = lut_path.replace('\\', '/').replace(':', '\\:')
                    lut_filter = f"lut3d=file='{safe_lut_path}',"

                filter_complex.append(
                    f"[{i}:v]{lut_filter}scale=640:360:force_original_aspect_ratio=decrease,"
                    f"pad=640:360:(ow-iw)/2:(oh-ih)/2[v{i}]"
                )
            else:
                # Match FPS and DURATION to avoid bottleneck and infinite loop
                # Apply -t to the input itself if possible, or use trim filter. 
                # Simplest for lavfi is adding duration to the input option or using -t before -i?
                # For lavfi, -t works as input option.
                duration_opt = ['-t', str(target_duration)] if target_duration > 0 else []
                input_args.extend(duration_opt)
                input_args.extend(['-f', 'lavfi', '-i', f'color=c=black:s=640x360:r={target_fps}'])
                filter_complex.append(f"[{i}:v]null[v{i}]")

        # 2. XStack
        layout = (
            "0_0|640_0|1280_0|"
            "0_360|640_360|1280_360|"
            "0_720|640_720|1280_720"
        )
        xstack_inputs = "".join([f"[v{i}]" for i in range(9)])
        filter_complex.append(f"{xstack_inputs}xstack=inputs=9:layout={layout}[stacked]")

        # 3. Draw Text
        final_tag = "out"
        if overlay_text:
            safe_text = overlay_text.replace(":", "\\:").replace("'", "")
            
            # Select Font for Mac
            font_path = "/System/Library/Fonts/Supplemental/AppleGothic.ttf"
            if not os.path.exists(font_path):
                 # Fallback
                 font_path = "/System/Library/Fonts/AppleSDGothicNeo.ttc"
            
            font_opt = f"fontfile='{font_path}':" if os.path.exists(font_path) else ""
            
            drawtext_filter = (
                f"drawtext=text='{safe_text}':{font_opt}fontcolor=white:fontsize=48:"
                f"x=(w-text_w)/2:y=h-80:box=1:boxcolor=black@0.5"
            )
            filter_complex.append(f"[stacked]{drawtext_filter}[{final_tag}]")
        else:
            final_tag = "stacked"

        # Construct final command
        cmd = [ffmpeg_exe, '-y']
        cmd.extend(input_args)
        cmd.extend(['-filter_complex', ";".join(filter_complex)])
        cmd.extend(['-map', f"[{final_tag}]"])
        
        # Encoding settings
        import platform
        if platform.system() == 'Darwin':
            # 0 = H.265 (HEVC), 1 = H.264
            is_hevc = codec_idx == 0 
            
            if is_hevc:
                cmd.extend(['-c:v', 'hevc_videotoolbox'])
                cmd.extend(['-b:v', '10M']) # Optimized for HEVC
                cmd.extend(['-tag:v', 'hvc1']) # Apple compatibility
            else:
                cmd.extend(['-c:v', 'h264_videotoolbox'])
                cmd.extend(['-b:v', '15M']) # Optimized for H.264 (Reduced from 20M)
        else:
            # Software Encoding (Windows/Linux) - Fallback
            cmd.extend(['-c:v', 'libx264'])
            cmd.extend(['-b:v', '15M'])
            cmd.extend(['-preset', 'fast'])
        
        if is_preview:
             cmd.extend(['-t', '1']) 
        else:
             cmd.append('-shortest')

        cmd.append(output_path)
        return cmd

    def find_ffprobe(self):
        """
        Attempts to find the FFprobe binary in common locations.
        """
        import shutil
        ffmpeg_bin = shutil.which("ffprobe")
        if ffmpeg_bin:
            return ffmpeg_bin
            
        common_paths = [
            "/Users/gimmyeongseob/Library/Python/3.9/lib/python/site-packages/static_ffmpeg/bin/darwin_arm64/ffprobe",
            "/usr/local/bin/ffprobe",
            "/opt/homebrew/bin/ffprobe",
            "/usr/bin/ffprobe"
        ]
        for path in common_paths:
            if os.path.exists(path):
                return path
        return "ffprobe"

    def get_fps(self, file_path):
        """
        Attempts to read the frame rate of the video file.
        Returns float (e.g. 60.0, 30.0) or default 30.0 if failed.
        """
        try:
            ffprobe_exe = self.find_ffprobe()
            cmd = [
                ffprobe_exe, 
                '-v', 'error', 
                '-select_streams', 'v:0',
                '-show_entries', 'stream=r_frame_rate', 
                '-of', 'default=noprint_wrappers=1:nokey=1', 
                file_path
            ]
            
            result = subprocess.run(
                cmd, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.PIPE, 
                text=True, 
                encoding='utf-8',
                errors='ignore',
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            
            if result.returncode == 0:
                fps_str = result.stdout.strip()
                # fps can be "60/1" or "30000/1001"
                if '/' in fps_str:
                    num, den = map(float, fps_str.split('/'))
                    if den > 0:
                        return num / den
                return float(fps_str)
            return 30.0 # Default fallback
        except Exception:
            return 30.0

    def get_duration(self, file_path):
        try:
            ffprobe_exe = self.find_ffprobe()
            cmd = [
                ffprobe_exe, 
                '-v', 'error', 
                '-show_entries', 'format=duration', 
                '-of', 'default=noprint_wrappers=1:nokey=1', 
                file_path
            ]
            # Use subprocess directly to ensure UTF-8 encoding is used for reading output
            # This prevents UnicodeDecodeError on Windows with Korean locale (cp949)
            result = subprocess.run(
                cmd, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.PIPE, 
                text=True, 
                encoding='utf-8',
                errors='ignore',
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            
            if result.returncode == 0:
                return float(result.stdout.strip())
            return 0.0
        except Exception:
            return 0.0
