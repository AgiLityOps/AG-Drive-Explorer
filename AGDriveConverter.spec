# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for the one-file Windows build. Needs bin/gltfpack.exe (build_exe.sh downloads it).
from PyInstaller.utils.hooks import collect_all

datas = [('viewer_template', 'viewer_template'), ('third_party', 'third_party'),
         ('THIRD_PARTY_NOTICES.md', '.'), ('LICENSE', '.')]
binaries = [('bin/gltfpack.exe', 'bin')]
hiddenimports = ['texture2ddecoder']
try:
    tmp_ret = collect_all('tkinterdnd2')          # optional drag-and-drop support
    datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
except Exception:
    pass

a = Analysis(['AGDriveConverter.py'], pathex=[], binaries=binaries, datas=datas, hiddenimports=hiddenimports,
             hookspath=[], hooksconfig={}, runtime_hooks=[],
             excludes=['matplotlib', 'scipy', 'pandas', 'IPython'], noarchive=False, optimize=0)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name='AGDriveConverter', debug=False,
          bootloader_ignore_signals=False, strip=False, upx=False, upx_exclude=[], runtime_tmpdir=None,
          console=False, disable_windowed_traceback=False, argv_emulation=False, target_arch=None,
          codesign_identity=None, entitlements_file=None)
