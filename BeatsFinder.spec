import os

# -*- mode: python ; coding: utf-8 -*-

project_dir = os.path.abspath(os.getcwd())
ffmpeg_dir = os.path.join(project_dir, "vendor", "ffmpeg")

binaries = []
if os.path.isfile(os.path.join(ffmpeg_dir, "ffmpeg.exe")):
    binaries.append((os.path.join(ffmpeg_dir, "ffmpeg.exe"), "ffmpeg"))
if os.path.isfile(os.path.join(ffmpeg_dir, "ffprobe.exe")):
    binaries.append((os.path.join(ffmpeg_dir, "ffprobe.exe"), "ffmpeg"))

datas = [(os.path.join(project_dir, "icon.ico"), ".")]

a = Analysis(
    ['beat_detector.py'],
    pathex=[project_dir],
    binaries=binaries,
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='BeatsFinder',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    icon=os.path.join(project_dir, 'icon.ico'),
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
