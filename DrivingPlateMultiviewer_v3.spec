# -*- mode: python ; coding: utf-8 -*-
import sys
sys.path.insert(0, SPECPATH)
from ffmpeg_engine import MultiviewerEngine
engine = MultiviewerEngine()
a = Analysis(['main.py'], pathex=[SPECPATH],
             binaries=[(engine.find_ffmpeg(), '.'), (engine.find_ffprobe(), '.')],
             datas=[], hiddenimports=[], hookspath=[], hooksconfig={}, runtime_hooks=[],
             excludes=[], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='DrivingPlateMultiviewer_v3',
          debug=False, strip=False, upx=False, console=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='DrivingPlateMultiviewer_v3')
app = BUNDLE(coll, name='DrivingPlateMultiviewer_v3.app',
             bundle_identifier='com.cjenmvp.drivingplate.multiviewer.v3',
             info_plist={'CFBundleShortVersionString': '3.0.0', 'NSHighResolutionCapable': True})
