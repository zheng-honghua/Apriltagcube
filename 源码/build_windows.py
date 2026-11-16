"""Build the portable Windows x64 app with the pinned build dependencies."""

import sys
import sysconfig
from importlib.metadata import distribution
from pathlib import Path

import PyInstaller.__main__


SOURCE = Path(__file__).resolve().parent
ROOT = SOURCE.parent


def main():
    if sysconfig.get_platform() != "win-amd64" or sys.version_info[:2] != (3, 13):
        raise SystemExit("Use Windows x64 Python 3.13 to build AprilTag Cube.")

    options = [
        "--noconfirm", "--windowed", "--onedir", "--noupx", "--name", "AprilTagCube",
        "--distpath", str(ROOT / "dist"), "--workpath", str(ROOT / "build"),
        "--specpath", str(ROOT / "build"), "--icon", str(SOURCE / "AppIcon.ico"),
    ]
    for name in ("families.json", "AppIcon.ico", "AprilTag-LICENSE.txt"):
        options.extend(["--add-data", f"{SOURCE / name}:."])

    # Keep the DLLs alongside OCP in the wheel's original relative directories.
    wheel = distribution("cadquery-ocp-novtk")
    for entry in wheel.files:
        if entry.suffix.lower() == ".dll":
            options.extend(["--add-binary", f"{wheel.locate_file(entry)}:{entry.parent}"])
        elif entry.name.startswith(".load-order"):
            options.extend(["--add-data", f"{wheel.locate_file(entry)}:{entry.parent}"])

    PyInstaller.__main__.run([*options, str(SOURCE / "windows_app.py")])


if __name__ == "__main__":
    main()
