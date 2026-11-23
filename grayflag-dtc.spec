# PyInstaller spec: one windowed-less (console) exe with the config, templates, datasets and web page bundled.
#   pyinstaller grayflag-dtc.spec
from PyInstaller.utils.hooks import collect_submodules

# The airframe plugins are imported by name at run time, so PyInstaller cannot see them: list every one here
# (and in grayflag_dtc/airframes/registry.py _KNOWN).
hidden = collect_submodules("uvicorn") + ["h11", "anyio._backends._asyncio",
                                          "grayflag_dtc.airframes.ah64d", "grayflag_dtc.airframes.f16c",
                                          "grayflag_dtc.airframes.fa18c"]
a = Analysis(
    ["grayflag-dtc.py"],
    pathex=["."],
    datas=[
        ("config", "config"),
        ("templates", "templates"),
        ("data/theaters", "data/theaters"),
        ("grayflag_dtc/static", "grayflag_dtc/static"),
        ("grayflag_dtc/harvest/harvester.lua", "grayflag_dtc/harvest"),
    ],
    hiddenimports=hidden,
    excludes=["tkinter", "matplotlib", "numpy"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name="grayflag-dtc", console=True, upx=False, icon="icon.ico")
