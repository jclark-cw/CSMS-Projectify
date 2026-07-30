"""PyInstaller entry point for the Projectify desktop app.

A separate file (not csms/desktop.py itself) so PyInstaller has a plain
top-level script to analyze; the actual app logic is unchanged and lives
in csms/desktop.py.
"""
from csms.desktop import main

if __name__ == "__main__":
    main()
