from __future__ import annotations

import os
import platform
import shutil
import subprocess
from pathlib import Path


class FolderPickerUnavailable(RuntimeError):
    pass


def choose_directory(initial: Path) -> Path | None:
    """Open the operating-system folder picker from the companion service."""
    system = platform.system()
    if system == "Windows":
        powershell = shutil.which("powershell.exe") or shutil.which("powershell")
        if not powershell:
            raise FolderPickerUnavailable("未找到 Windows 文件夹选择器")
        script = (
            "[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
            "$shell=New-Object -ComObject Shell.Application;"
            "$folder=$shell.BrowseForFolder(0,'选择 PaperNote 笔记库文件夹',0,$env:PAPERNOTE_PICKER_INITIAL);"
            "if($folder){[Console]::Write($folder.Self.Path)}"
        )
        env = os.environ.copy()
        env["PAPERNOTE_PICKER_INITIAL"] = str(initial)
        completed = subprocess.run(
            [powershell, "-NoProfile", "-STA", "-Command", script],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=180, env=env, check=False,
        )
        if completed.returncode:
            raise FolderPickerUnavailable(completed.stderr.strip() or "Windows 文件夹选择器启动失败")
        value = completed.stdout.strip().lstrip("\ufeff")
        return Path(value) if value else None
    if system == "Darwin":
        completed = subprocess.run(
            ["osascript", "-e", 'POSIX path of (choose folder with prompt "选择 PaperNote 笔记库文件夹")'],
            capture_output=True, text=True, timeout=180, check=False,
        )
        if completed.returncode:
            if "User canceled" in completed.stderr:
                return None
            raise FolderPickerUnavailable(completed.stderr.strip() or "macOS 文件夹选择器启动失败")
        return Path(completed.stdout.strip()) if completed.stdout.strip() else None
    zenity = shutil.which("zenity")
    if zenity:
        completed = subprocess.run(
            [zenity, "--file-selection", "--directory", "--title=选择 PaperNote 笔记库文件夹", f"--filename={initial}/"],
            capture_output=True, text=True, timeout=180, check=False,
        )
        return Path(completed.stdout.strip()) if completed.returncode == 0 and completed.stdout.strip() else None
    kdialog = shutil.which("kdialog")
    if kdialog:
        completed = subprocess.run(
            [kdialog, "--getexistingdirectory", str(initial), "--title", "选择 PaperNote 笔记库文件夹"],
            capture_output=True, text=True, timeout=180, check=False,
        )
        return Path(completed.stdout.strip()) if completed.returncode == 0 and completed.stdout.strip() else None
    raise FolderPickerUnavailable(
        "当前 Linux 桌面未安装文件夹选择器；请安装 zenity 或 kdialog，"
        "也可以通过 PAPERNOTE_DATA_DIR 环境变量指定笔记库位置"
    )
