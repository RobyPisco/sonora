# PyInstaller spec — Sonora (onedir).
# Build:  pyinstaller build.spec --noconfirm
# Output: dist/Sonora/Sonora.exe  (distribuire l'intera cartella, es. in zip)
#
# Onedir scelto su onefile perche' ffmpeg/ffprobe (~190MB) verrebbero
# estratti nel temp a ogni avvio in modalita' onefile -> avvio lento.

import re
from pathlib import Path

from PyInstaller.utils.hooks import collect_dynamic_libs

project = Path(SPECPATH)

# --- info-versione native dell'exe (Proprietà → Dettagli su Windows) ---
_ver = re.search(r'__version__\s*=\s*"([^"]+)"',
                 (project / "app" / "__init__.py").read_text(encoding="utf-8")).group(1)
_vt = tuple(int(x) for x in _ver.split(".")) + (0, 0, 0, 0)
_vt = _vt[:4]
try:
    from PyInstaller.utils.win32.versioninfo import (
        FixedFileInfo, StringFileInfo, StringStruct, StringTable,
        VarFileInfo, VarStruct, VSVersionInfo,
    )
    _vinfo = VSVersionInfo(
        ffi=FixedFileInfo(filevers=_vt, prodvers=_vt, mask=0x3F, flags=0x0,
                          OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
        kids=[
            StringFileInfo([StringTable("040904B0", [
                StringStruct("CompanyName", "Pisco Factory"),
                StringStruct("FileDescription", "Sonora — audio downloader & stem practice"),
                StringStruct("FileVersion", _ver),
                StringStruct("InternalName", "Sonora"),
                StringStruct("LegalCopyright", "© 2026 Pisco Factory"),
                StringStruct("OriginalFilename", "Sonora.exe"),
                StringStruct("ProductName", "Sonora"),
                StringStruct("ProductVersion", _ver),
            ])]),
            VarFileInfo([VarStruct("Translation", [1033, 1200])]),
        ],
    )
    _version_file = project / "build" / "file_version_info.txt"
    _version_file.parent.mkdir(parents=True, exist_ok=True)
    _version_file.write_text(str(_vinfo), encoding="utf-8")
    _exe_version = str(_version_file)
except Exception:
    _exe_version = None

datas = [
    (str(project / "bin" / "ffmpeg.exe"), "bin"),
    (str(project / "bin" / "ffprobe.exe"), "bin"),
    (str(project / "bin" / "uv.exe"), "bin"),
    (str(project / "bin" / "rubberband.exe"), "bin"),
    (str(project / "bin" / "rubberband-r3.exe"), "bin"),
    (str(project / "bin" / "sndfile.dll"), "bin"),
    # script eseguiti dal venv del motore (file sorgente reali)
    (str(project / "app" / "analyze_script.py"), "app_scripts"),
    (str(project / "app" / "roformer_script.py"), "app_scripts"),
]

# includi tutti i file in resources/ (qss, svg, ico)
for res in (project / "resources").iterdir():
    if res.is_file():
        datas.append((str(res), "resources"))

# DLL native delle librerie audio (libsndfile / portaudio)
binaries = []
for _pkg in ("soundfile", "sounddevice", "_sounddevice_data"):
    try:
        binaries += collect_dynamic_libs(_pkg)
    except Exception:
        pass

icon_file = project / "resources" / "icon.ico"

a = Analysis(
    ["run.py"],
    pathex=[str(project)],
    binaries=binaries,
    datas=datas,
    hiddenimports=["yt_dlp", "psutil", "numpy", "soundfile", "sounddevice",
                   "cffi", "_cffi_backend"],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "PySide6.QtQuick", "PySide6.QtQml", "PySide6.Qt3DCore",
        "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
        "PySide6.QtMultimedia", "PySide6.QtCharts", "PySide6.QtDataVisualization",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Sonora",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,                       # app GUI, niente finestra console
    icon=str(icon_file) if icon_file.exists() else None,
    version=_exe_version,                 # info-versione/azienda native
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Sonora",
)
