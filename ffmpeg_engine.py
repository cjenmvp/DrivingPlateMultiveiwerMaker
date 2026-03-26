import os
import re
import ffmpeg
import subprocess
import json
import unicodedata

class MultiviewerEngine:
    def __init__(self):
        # 3x3 Grid Matrix (Row-major)
        self.slot_patterns = {
            0: ["10_"],         # Row 1-1
            1: ["12_"],         # Row 1-2
            2: ["02_"],         # Row 1-3
            3: ["09_"],         # Row 2-1
            4: ["Top_", "13_"], # Row 2-2 (Center)
            5: ["03_"],         # Row 2-3
            6: ["08_"],         # Row 3-1
            7: ["06_"],         # Row 3-2
            8: ["04_"]          # Row 3-3
        }
        
    def scan_folder(self, folder_path):
        if not os.path.exists(folder_path):
            return {}

        # 경로 정규화 (NFC)
        folder_path = unicodedata.normalize('NFC', folder_path)
        files = os.listdir(folder_path)
        video_extensions = ('.mp4', '.mov', '.mkv', '.avi')
        video_files = [f for f in files if f.lower().endswith(video_extensions) and not f.startswith('.')]
        
        mapping = {i: None for i in range(9)}

        for slot, patterns in self.slot_patterns.items():
            for pattern in patterns:
                match = next((f for f in video_files if f.startswith(pattern) or f"_{pattern}" in f), None)
                if match:
                    mapping[slot] = os.path.join(folder_path, match)
                    break
        
        return mapping

    def find_ffmpeg(self):
        import shutil
        ffmpeg_bin = shutil.which("ffmpeg")
        if ffmpeg_bin:
            return ffmpeg_bin
            
        try:
            import static_ffmpeg
            static_ffmpeg.add_paths()
            ffmpeg_bin = shutil.which("ffmpeg")
            if ffmpeg_bin:
                return ffmpeg_bin
        except ImportError:
            pass
            
        common_paths = [
            "/Users/gimmyeongseob/Library/Python/3.9/lib/python/site-packages/static_ffmpeg/bin/darwin_arm64/ffmpeg",
            "/usr/local/bin/ffmpeg",
            "/opt/homebrew/bin/ffmpeg"
        ]
        for path in common_paths:
            if os.path.exists(path):
                return path
        return "ffmpeg"

    def build_command(self, file_mapping, output_path, overlay_text="", is_preview=False, codec_idx=0, lut_mapping=None):
        if lut_mapping is None:
            lut_mapping = {}
        
        ffmpeg_exe = self.find_ffmpeg()
        filter_complex = []
        input_args = []
        
        # Determine target properties
        target_fps = 30.0
        target_duration = 0.0
        
        def safe_path(p):
            if not p: return p
            return unicodedata.normalize('NFC', os.path.abspath(p))

        for i in range(9):
             path = file_mapping.get(i)
             if path:
                 path = safe_path(path)
                 target_fps = self.get_fps(path)
                 target_duration = self.get_duration(path)
                 break
                 
        for i in range(9):
            file_path = file_mapping.get(i)
            if file_path:
                file_path = safe_path(file_path)
                input_args.extend(['-i', file_path])
                
                lut_filter = ""
                if i in lut_mapping and lut_mapping[i]:
                    lut_p = safe_path(lut_mapping[i])
                    # FFmpeg filter escape
                    safe_lut_p = lut_p.replace('\\', '/').replace(':', '\\:').replace("'", "'\\\\\\''")
                    lut_filter = f"lut3d=file='{safe_lut_p}',"

                filter_complex.append(
                    f"[{i}:v]{lut_filter}scale=640:360:force_original_aspect_ratio=decrease,"
                    f"pad=640:360:(ow-iw)/2:(oh-ih)/2[v{i}]"
                )
            else:
                duration_opt = ['-t', str(target_duration)] if target_duration > 0 else []
                input_args.extend(duration_opt)
                input_args.extend(['-f', 'lavfi', '-i', f'color=c=black:s=640x360:r={target_fps}'])
                filter_complex.append(f"[{i}:v]null[v{i}]")

        layout = "0_0|640_0|1280_0|0_360|640_360|1280_360|0_720|640_720|1280_720"
        xstack_inputs = "".join([f"[v{i}]" for i in range(9)])
        filter_complex.append(f"{xstack_inputs}xstack=inputs=9:layout={layout}[stacked]")

        final_tag = "out"
        if overlay_text:
            # 장소명에서 깔끔하게 끝나도록 특수문자 제거
            clean_text = overlay_text.strip().replace(":", "\\:").replace("'", "")
            font_path = "/System/Library/Fonts/Supplemental/AppleGothic.ttf"
            if not os.path.exists(font_path):
                 font_path = "/System/Library/Fonts/AppleSDGothicNeo.ttc"
            
            font_opt = f"fontfile='{font_path}':" if os.path.exists(font_path) else ""
            drawtext_filter = (
                f"drawtext=text='{clean_text}':{font_opt}fontcolor=white:fontsize=48:"
                f"x=(w-text_w)/2:y=h-80:box=1:boxcolor=black@0.5"
            )
            filter_complex.append(f"[stacked]{drawtext_filter}[{final_tag}]")
        else:
            final_tag = "stacked"

        cmd = [ffmpeg_exe, '-y']
        cmd.extend(input_args)
        cmd.extend(['-filter_complex', ";".join(filter_complex)])
        cmd.extend(['-map', f"[{final_tag}]"])
        
        output_path = safe_path(output_path)
        import platform
        if platform.system() == 'Darwin':
            if codec_idx == 0: # HEVC
                cmd.extend(['-c:v', 'hevc_videotoolbox', '-b:v', '10M', '-tag:v', 'hvc1'])
            else: # H.264
                cmd.extend(['-c:v', 'h264_videotoolbox', '-b:v', '15M'])
        else:
            cmd.extend(['-c:v', 'libx264', '-b:v', '15M', '-preset', 'fast'])
        
        if is_preview: cmd.extend(['-t', '1'])
        else: cmd.append('-shortest')

        cmd.append(output_path)
        return cmd

    def find_ffprobe(self):
        import shutil
        bin = shutil.which("ffprobe")
        if bin: return bin
        common = ["/Users/gimmyeongseob/Library/Python/3.9/lib/python/site-packages/static_ffmpeg/bin/darwin_arm64/ffprobe", "/usr/local/bin/ffprobe", "/opt/homebrew/bin/ffprobe"]
        for p in common:
            if os.path.exists(p): return p
        return "ffprobe"

    def get_fps(self, file_path):
        try:
            cmd = [self.find_ffprobe(), '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=r_frame_rate', '-of', 'default=noprint_wrappers=1:nokey=1', file_path]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors='ignore')
            if res.returncode == 0:
                fps_str = res.stdout.strip()
                if '/' in fps_str:
                    n, d = map(float, fps_str.split('/'))
                    return n / d if d > 0 else 30.0
                return float(fps_str)
            return 30.0
        except: return 30.0

    def get_duration(self, file_path):
        try:
            cmd = [self.find_ffprobe(), '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', file_path]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors='ignore')
            return float(res.stdout.strip()) if res.returncode == 0 else 0.0
        except: return 0.0
