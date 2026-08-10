"""PyInstaller entry point for the Projectify desktop app.

A separate file (not csms/desktop.py itself) so PyInstaller has a plain
top-level script to analyze; the actual app logic is unchanged and lives
in csms/desktop.py.

`--selftest` runs the frozen bundle headlessly and exits non-zero if anything
the app needs at runtime failed to get bundled. This is the check that matters
for a frozen build: PyInstaller happily produces an .exe whose missing data
files only surface when the tester opens their first contract. CI runs it so
that failure lands in the build log instead of on the client's PC.
"""

import sys


def _selftest(sample_pdf=None) -> int:
    """Exercise the bundled-resource paths that static analysis can't see.

    `sample_pdf` is an optional path to a real contract, parsed end to end. CI
    passes one from the repo checkout rather than bundling it, so the client's
    app ships without sample contracts in it.

    Writes a report to selftest.log because the app is frozen --windowed: on
    Windows there is no console attached, so stdout would go nowhere and a CI
    failure would be undebuggable.
    """
    results = []

    def check(label, fn):
        """Run fn; whatever it returns is shown as detail next to the result."""
        try:
            detail = fn()
        except Exception as e:
            results.append(("FAIL", label, f"{type(e).__name__}: {e}"))
        else:
            results.append(("ok", label, detail or ""))

    def _pdf_data_files():
        # The CMap tables ship as package data. If they were dropped, this
        # raises -- and the app would otherwise fail on the first PDF opened.
        from pdfminer.cmapdb import CMapDB
        CMapDB.get_cmap("90ms-RKSJ-H")

    def _parser():
        from csms.parser import parse_contract, validate_pdf  # noqa: F401

    def _keychain():
        # No backend => the setup wizard cannot store the client's Asana PAT.
        import keyring
        backend = keyring.get_keyring()
        if backend is None or "fail" in type(backend).__name__.lower():
            raise RuntimeError(f"no usable keyring backend: {backend!r}")

    def _flask_app():
        # Builds the real app and renders the first-run page end to end.
        from csms.webapp import create_app
        app = create_app(desktop=True)
        client = app.test_client()
        resp = client.get("/")
        if resp.status_code not in (200, 302):
            raise RuntimeError(f"GET / returned {resp.status_code}")

    def _webview():
        import webview  # noqa: F401

    def _parse_sample():
        # The definitive check: a real contract through the real parser, in the
        # frozen bundle. Everything above can pass while this still fails.
        from csms.parser import parse_contract, validate_pdf
        validate_pdf(sample_pdf)
        sections = parse_contract(sample_pdf)
        if not sections:
            raise RuntimeError("parsed 0 sections from the sample contract")
        tasks = sum(len(s.get("tasks", [])) for s in sections)
        if not tasks:
            raise RuntimeError(f"parsed {len(sections)} sections but 0 tasks")
        return f"{len(sections)} sections, {tasks} tasks"

    check("pdfminer cmap data files", _pdf_data_files)
    check("csms.parser imports", _parser)
    check("keyring backend resolves", _keychain)
    check("flask app builds + serves /", _flask_app)
    check("pywebview imports", _webview)
    if sample_pdf:
        check(f"end-to-end parse of {sample_pdf}", _parse_sample)

    failed = [r for r in results if r[0] == "FAIL"]
    report = "\n".join(
        f"[{status}] {label}{(' — ' + detail) if detail else ''}"
        for status, label, detail in results
    )
    report += f"\n\n{len(results) - len(failed)}/{len(results)} checks passed\n"

    try:
        with open("selftest.log", "w", encoding="utf-8") as f:
            f.write(report)
    except OSError:
        pass
    print(report)

    return 1 if failed else 0


def main():
    if "--selftest" in sys.argv:
        args = sys.argv[sys.argv.index("--selftest") + 1:]
        sys.exit(_selftest(args[0] if args else None))
    from csms.desktop import main as desktop_main
    desktop_main()


if __name__ == "__main__":
    main()
