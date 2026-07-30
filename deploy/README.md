# Auto-trigger deployment

The DocuSign auto-trigger has two ways to fire — both run the same `csms poll`
command (which calls `poll_once()`); neither needs a public web server.

## Manual / instant (no setup)

```bash
python3 -m csms poll                 # process envelopes completed in the last day
python3 -m csms poll --since 2026-01-01
python3 -m csms poll --playbook playbook.yaml
```

Needs the `DOCUSIGN_*` keys in `.env` (and `requirements-docusign.txt`). Without
them it exits with a clear message. This is the "run it now" button in CLI form.

## Scheduled poll (macOS launchd)

Runs `csms poll` on an interval. Outbound only — no public endpoint.

```bash
# 1. Edit deploy/com.csms.poll.plist — set the python path, WorkingDirectory,
#    and StartInterval (seconds).
# 2. Install:
cp deploy/com.csms.poll.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.csms.poll.plist
# 3. Logs: state/poll.log and state/poll.err.log
# To stop:
launchctl unload ~/Library/LaunchAgents/com.csms.poll.plist
```

Caveat: launchd only fires while the machine is awake. For 24/7 independent of a
laptop, run `csms poll` from a cron on a small always-on box / cloud cron instead
(still outbound only — no hosting of a public endpoint).

## Webhook (only if chosen later)

Real-time, but needs a public HTTPS endpoint + HMAC verification — i.e. actual
hosting. Would add a verified `/webhook/docusign` route to the Flask app and deploy it.
