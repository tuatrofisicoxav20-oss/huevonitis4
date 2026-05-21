# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for Huevonitis 4.
Build: pyinstaller build/huevonitis4.spec --distpath dist --workpath build/work
"""
from PyInstaller.utils.hooks import collect_all
import sys, os

block_cipher = None

# Collect ALL customtkinter assets (themes, fonts, images)
ctk_datas, ctk_binaries, ctk_hiddenimports = collect_all("customtkinter")

# PIL / Pillow plugins
pil_datas, pil_binaries, pil_hiddenimports = collect_all("PIL")

datas = [
    ("assets/icon.png",  "assets"),
    ("assets/icon.ico",  "assets"),
]
datas += ctk_datas + pil_datas

binaries = ctk_binaries + pil_binaries

hiddenimports = ctk_hiddenimports + pil_hiddenimports + [
    "cv2", "numpy", "pytesseract", "docx", "reportlab",
    "reportlab.pdfgen", "reportlab.platypus", "reportlab.lib",
    "lxml", "lxml.etree",
    "tkinter", "tkinter.ttk", "tkinter.messagebox", "tkinter.filedialog",
    "_tkinter",
]

a = Analysis(
    ["../main.py"],
    pathex=[".."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["matplotlib", "scipy", "pandas", "jupyter", "IPython"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="huevonitis4",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,              # No terminal window
    icon="../assets/icon.ico",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="huevonitis4",
)
