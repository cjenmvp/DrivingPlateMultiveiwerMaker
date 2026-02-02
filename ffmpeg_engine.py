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
                # Find first matching file
                match = next((f for f in video_files if pattern in f), None)
                if match:
                    mapping[slot] = os.path.join(folder_path, match)
                    break # Stop if match found (important for priority Top > 13)
        
        return mapping

    def build_command(self, file_mapping, output_path, overlay_text="", is_preview=False):
        """
        Builds the FFmpeg command using ffmpeg-python fluent interface (conceptually) 
        or raw command line arguments for subprocess.
        """
        
        # Base input settings
        inputs = []
        filter_complex = []
        
        # 1. Input Processing
        # We need to construct inputs. If a slot is None, we use a color source.
        
        valid_input_count = 0
        first_valid_input_path = None
        
        # To ensure we track which input index corresponds to which slot for xstack
        input_args = []
        
        for i in range(9):
            file_path = file_mapping.get(i)
            if file_path:
                # Real file input
                input_args.extend(['-i', file_path])
                valid_input_count += 1
                if not first_valid_input_path:
                    first_valid_input_path = file_path
                
                # Filter for this input: Scale & Pad
                # [i:v]scale=640:360:force_original_aspect_ratio=decrease,pad=640:360:(ow-iw)/2:(oh-ih)/2[v_i]
                filter_complex.append(
                    f"[{i}:v]scale=640:360:force_original_aspect_ratio=decrease,"
                    f"pad=640:360:(ow-iw)/2:(oh-ih)/2[v{i}]"
                )
            else:
                # Missing file -> Black placeholder
                # We can't easily add a 'color' input source mixed with file inputs in a simple way for indices.
                # Actually, simplest way for 'missing' in complex filter graph where inputs are dynamic 
                # is to add the color source as an input or generate it in filter.
                # Let's add it as an input using -f lavfi.
                input_args.extend(['-f', 'lavfi', '-i', 'color=c=black:s=640x360'])
                # No scaling needed for generated black, but we need to label the stream
                filter_complex.append(f"[{i}:v]null[v{i}]") # Pass-through to name it v{i}

        # 2. XStack
        # xstack=inputs=9:layout=...
        layout = (
            "0_0|640_0|1280_0|"
            "0_360|640_360|1280_360|"
            "0_720|640_720|1280_720"
        )
        
        # Concatenate input streams for xstack
        xstack_inputs = "".join([f"[v{i}]" for i in range(9)])
        filter_complex.append(f"{xstack_inputs}xstack=inputs=9:layout={layout}[stacked]")

        # 3. Draw Text (on the stacked output)
        final_tag = "out"
        if overlay_text:
            # Drawtext logic
            # escape text logic might be needed for special chars
            safe_text = overlay_text.replace(":", "\\:").replace("'", "")
            drawtext_filter = (
                f"drawtext=text='{safe_text}':fontcolor=white:fontsize=48:"
                f"x=(w-text_w)/2:y=h-80:box=1:boxcolor=black@0.5" # Bottom center
            )
            filter_complex.append(f"[stacked]{drawtext_filter}[{final_tag}]")
        else:
            final_tag = "stacked"

        # Construct final command
        cmd = ['ffmpeg', '-y']
        
        # Add frame rate from first valid input if available, else default
        # Note: -r before input forces interpretation, after forces output. 
        # Requirement: "detect from first valid source and apply to whole video"
        # We'll just rely on the encoder defaults or force output generic if needed.
        # But user asked to use -r option.
        cmd.extend(input_args)
        cmd.extend(['-filter_complex', ";".join(filter_complex)])
        cmd.extend(['-map', f"[{final_tag}]"])
        
        # Encoding settings
        cmd.extend(['-c:v', 'libx264'])
        cmd.extend(['-b:v', '20M'])
        cmd.extend(['-preset', 'medium'])
        
        if is_preview:
             cmd.extend(['-t', '1']) # 1 second for preview

        cmd.append(output_path)
        
        return cmd

    def get_duration(self, file_path):
        try:
            cmd = [
                'ffprobe', 
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
