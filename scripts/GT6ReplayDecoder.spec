from pathlib import Path

ROOT = Path(SPECPATH).parent
notices = ["LICENSE", "THIRD_PARTY.md", "Python-LICENSE.txt", "PDTools-MIT.txt",
           "Qt-LGPL-3.0-only.txt", "Qt-GPL-2.0-only.txt", "Qt-GPL-3.0-only.txt", "third-party-sources.json"]
datas = [(str(ROOT / "LICENSES"), "LICENSES"), (str(ROOT / "src/assets"), "assets")]
datas += [(str(ROOT / name), "LICENSES") for name in notices]
a = Analysis([str(ROOT / "src/decoder_program.py")], pathex=[str(ROOT / "src")],
             binaries=[], datas=datas, hiddenimports=[], hookspath=[], hooksconfig={},
             runtime_hooks=[], excludes=[], noarchive=False, optimize=0)
excluded = ("qt6virtualkeyboard", "qt6pdf", "qt6qml", "qt6quick", "qtvirtualkeyboardplugin", "qpdf")
a.binaries = [entry for entry in a.binaries if not any(Path(entry[0]).name.lower().startswith(prefix) for prefix in excluded)]
pyz = PYZ(a.pure)
gui = EXE(pyz, a.scripts, [], exclude_binaries=True, name="GT6ReplayDecoder", debug=False,
          strip=False, upx=False, console=False, icon=str(ROOT / "src/assets/icon.ico"))
cli = EXE(pyz, a.scripts, [], exclude_binaries=True, name="GT6ReplayDecoderCLI", debug=False,
          strip=False, upx=False, console=True, icon=str(ROOT / "src/assets/icon.ico"))
coll = COLLECT(gui, cli, a.binaries, a.datas, strip=False, upx=False, name="GT6ReplayDecoder")
