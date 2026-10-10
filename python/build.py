# -*- coding: utf-8 -*-
"""把离线程序打成单个可执行文件。Windows 上产物是 watchman.exe，macOS 上是 watchman。"""
import os
import platform
import shutil
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def main():
    cli = os.path.join(os.path.dirname(__file__), "cli.py")
    modules = os.path.join(ROOT, "modules")
    sep = os.pathsep
    add = modules + sep + "modules"
    dist = os.path.join(ROOT, "dist")
    work = os.path.join(ROOT, "build-py")
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean", "--onefile",
        "--name", "watchman-py",
        "--distpath", dist,
        "--workpath", work,
        "--specpath", work,
        "--add-data", add,
        "--hidden-import", "yaml",
        cli,
    ]
    subprocess.check_call(cmd, cwd=ROOT)
    name = "watchman-py.exe" if platform.system() == "Windows" else "watchman-py"
    exe = os.path.join(dist, name)
    if not os.path.isfile(exe):
        raise SystemExit("未找到产物: " + exe)
    print(exe)
    print(os.path.getsize(exe))


if __name__ == "__main__":
    if not shutil.which(sys.executable):
        raise SystemExit("没有 python")
    main()
