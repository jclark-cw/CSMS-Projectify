#!/usr/bin/env python3
"""csms.desktop — Projectify as a native desktop window (PyWebview).

The SAME Flask app as the web version, wrapped in a local OS window — no browser,
no visible URL. This is the local-app form and the click-install precursor: freeze
this with PyInstaller later for a double-click app. Cross-platform backends:
WebKit (macOS), EdgeWebView2 (Windows), GTK/Qt (Linux).

Run:  python3 -m csms.desktop
"""

from __future__ import annotations

import webview

from .webapp import create_app


def main():
    # PyWebview serves the Flask app on an internal loopback server and renders it
    # in a native window — the user never sees a URL. desktop=True gates the
    # first-run Asana setup wizard and reads creds from the OS keychain, not .env
    # (each client's own install must write to their own Asana, not ours).
    app = create_app(desktop=True)
    webview.create_window(
        "Projectify — Contract → Asana",
        app,
        width=920,
        height=860,
        min_size=(640, 600),
    )
    webview.start()


if __name__ == "__main__":
    main()
