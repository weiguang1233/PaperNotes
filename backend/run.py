from __future__ import annotations

import os
import socket
import threading
import time
import webbrowser

import uvicorn


def choose_port() -> int:
    try:
        requested = int(os.environ.get("PAPERNOTE_PORT", "8765"))
    except ValueError:
        requested = 8765
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind(("127.0.0.1", requested))
        return requested
    except OSError:
        probe.close()
        fallback = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        fallback.bind(("127.0.0.1", 0))
        port = int(fallback.getsockname()[1])
        fallback.close()
        print(f"端口 {requested} 已被占用，服务改用端口 {port}。", flush=True)
        return port
    finally:
        try:
            probe.close()
        except OSError:
            pass


def open_browser(port: int) -> None:
    time.sleep(1.2)
    webbrowser.open(f"http://127.0.0.1:{port}/?mode=server")


if __name__ == "__main__":
    port = choose_port()
    if os.environ.get("PAPERNOTE_NO_BROWSER") != "1":
        threading.Thread(target=open_browser, args=(port,), daemon=True).start()
    uvicorn.run("backend.app.main:app", host="127.0.0.1", port=port, reload=False, access_log=False)
