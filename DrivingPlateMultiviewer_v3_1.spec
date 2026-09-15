# -*- mode: python ; coding: utf-8 -*-
import sys
sys.path.insert(0, SPECPATH)
from ffmpeg_engine import MultiviewerEngine
from version import __version__
APP_NAME = 'DrivingPlateMultiviewer_v' + __version__.replace('.', '_')
engine = MultiviewerEngine()
a = Analysis(['main.py'], pathex=[SPECPATH],
             binaries=[(engine.find_ffmpeg(), '.'), (engine.find_ffprobe(), '.')],
             datas=[], hiddenimports=[], hookspath=[], hooksconfig={}, runtime_hooks=[],
             excludes=[], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name=APP_NAME,
          debug=False, strip=False, upx=False, console=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name=APP_NAME)
app = BUNDLE(coll, name=APP_NAME + '.app',
             bundle_identifier='com.cjenmvp.drivingplate.multiviewer.v3',
             info_plist={'CFBundleShortVersionString': __version__, 'NSHighResolutionCapable': True})
