"""Unified PaperNote launcher for Windows, macOS, and Linux."""

from __future__ import annotations

import argparse
import os
import platform
import runpy
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
ZOTERO_PROBE_URL = "http://127.0.0.1:23119/api/users/0/items?limit=1"


def probe_zotero(timeout: float = 1.5) -> tuple[bool, str]:
    request = Request(
        ZOTERO_PROBE_URL,
        headers={"Accept": "application/json", "Zotero-API-Version": "3", "User-Agent": "PaperNote/1.0"},
        method="GET",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            response.read(1)
        return True, "Zotero Local API 已连接"
    except HTTPError as exc:
        if exc.code == 403:
            return False, "Zotero 已运行，但 Local API 未授权（HTTP 403）"
        return False, f"Zotero Local API 返回 HTTP {exc.code}"
    except (URLError, TimeoutError, OSError):
        return False, "Zotero Local API 尚未启动"


def zotero_launch_command() -> list[str] | None:
    system = platform.system()
    if system == "Windows":
        candidates = [
            Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Zotero" / "zotero.exe",
            Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Zotero" / "zotero.exe",
        ]
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            candidates.append(Path(local_app_data) / "Zotero" / "zotero.exe")
        return next(([str(path)] for path in candidates if path.is_file()), None)
    if system == "Darwin":
        return ["open", "-a", "Zotero"] if Path("/Applications/Zotero.app").exists() else None
    executable = shutil.which("zotero")
    return [executable] if executable else None


def ensure_zotero(wait_seconds: float = 18.0) -> tuple[bool, str]:
    ready, detail = probe_zotero()
    if ready:
        return ready, detail
    command = zotero_launch_command()
    if command is None:
        return False, detail + "；未找到 Zotero 桌面程序"
    print("正在启动 Zotero，并等待 Local API……", flush=True)
    try:
        subprocess.Popen(
            command,
            cwd=str(ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as exc:
        return False, f"无法启动 Zotero：{exc}"
    deadline = time.monotonic() + wait_seconds
    last_detail = detail
    while time.monotonic() < deadline:
        time.sleep(0.75)
        ready, last_detail = probe_zotero()
        if ready or "403" in last_detail:
            return ready, last_detail
    return False, last_detail


def start_server(port: int, no_browser: bool, connect_zotero: bool = True) -> None:
    if connect_zotero:
        ready, detail = ensure_zotero()
        print(detail + "。", flush=True)
        if not ready:
            print("PaperNote 仍会启动；请在 Zotero 高级设置中启用 Local API 后再测试连接。", flush=True)
    else:
        print("PaperNote 离线模式：科研笔记仍直接读写 Markdown；不会连接 Zotero 或互联网。", flush=True)
    os.environ["PAPERNOTE_PORT"] = str(port)
    if no_browser:
        os.environ["PAPERNOTE_NO_BROWSER"] = "1"
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    runpy.run_module("backend.run", run_name="__main__")


def main() -> None:
    parser = argparse.ArgumentParser(description="Start PaperNote")
    parser.add_argument("--mode", choices=("server", "local"), default="server")
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    start_server(args.port or (8765 if args.mode == "local" else 8766), args.no_browser, connect_zotero=args.mode == "server")


if __name__ == "__main__":
    main()
