# ops/

Operational tooling for Rez Ops. Sibling to `connectors/`/`ledger_core/` —
this directory is neither a Sensor nor the Ledger, it's the plumbing that
runs the periodic briefing (CAP-7) unattended, on an OS schedule (CAP-8,
AD-7).

## `run_scheduled_briefing.py`

Invokes `claude -p --mcp-config .mcp.json --output-format json` (never
`--bare` — `--bare` skips MCP-server autodiscovery entirely and would run
the briefing with no Sensors or Ledger attached) with a fixed prompt asking
for the periodic briefing, under a wall-clock timeout.

- **Success** (exit 0, valid JSON on stdout): the wrapper exits 0 and writes
  nothing. The briefing's content is not this script's concern — only that
  the run happened.
- **Failure** (non-zero exit, a timeout, or stdout that isn't valid JSON):
  the wrapper appends exactly one entry to `ledger_data/_ops.log.md` —
  timestamp (UTC) plus a failure reason (`timeout`, `nonzero_exit`, or
  `malformed_output`) — and exits non-zero. `_ops.log.md` is append-only:
  existing entries are never rewritten, and the file is created on first
  failure if it doesn't exist yet.
- No retry/backoff: one invocation, one outcome, logged.

Run it manually to check it works before scheduling anything:

```bash
cd /path/to/rez-ops
uv run python ops/run_scheduled_briefing.py; echo "exit: $?"
```

## Registering a schedule (manual step — nothing is installed by this story)

Neither of the snippets below is applied automatically. Registering a
schedule on this or any machine is a deliberate, manual step left to a
human.

Both examples assume `claude` is on `PATH` for the user/session the
scheduler runs as, and that connector credentials (`REZOPS_*_TOKEN` env
vars, or OS keychain entries — see the top-level `README.md`) are available
in that same environment. Cron and launchd both typically run with a
minimal environment, not your interactive shell's — set credentials
explicitly in the job definition, or via `launchctl setenv` / a wrapper
script, rather than assuming they're inherited.

### cron

Edit the crontab for the user that should run the job (`crontab -e`), and
add a line such as:

```cron
# Run the periodic Rez Ops briefing every weekday at 07:00 local time.
0 7 * * 1-5 cd /path/to/rez-ops && /path/to/uv run python ops/run_scheduled_briefing.py >> /path/to/rez-ops/ledger_data/_cron_stdout.log 2>&1
```

Use absolute paths for the repo (`cd /path/to/rez-ops`), `uv` (`/path/to/uv`,
e.g. the output of `which uv`), *and* `claude` (`which claude`) — cron's
`PATH` is usually much shorter than an interactive shell's, and the wrapper
invokes `claude` by its bare name (see `ops/run_scheduled_briefing.py`), so
it's subject to the identical "not found on this minimal `PATH`" problem as
`uv`. Set `PATH` explicitly in the crontab (or symlink `claude` somewhere
already on cron's default `PATH`) so the bare `claude` invocation inside the
wrapper can still find the binary.

### launchd (macOS)

Create a plist such as `~/Library/LaunchAgents/com.rezops.scheduled-briefing.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.rezops.scheduled-briefing</string>
  <key>ProgramArguments</key>
  <array>
    <string>/path/to/uv</string>
    <string>run</string>
    <string>python</string>
    <string>ops/run_scheduled_briefing.py</string>
  </array>
  <key>WorkingDirectory</key>
  <string>/path/to/rez-ops</string>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key>
    <integer>7</integer>
    <key>Minute</key>
    <integer>0</integer>
  </dict>
  <key>StandardOutPath</key>
  <string>/path/to/rez-ops/ledger_data/_launchd_stdout.log</string>
  <key>StandardErrorPath</key>
  <string>/path/to/rez-ops/ledger_data/_launchd_stderr.log</string>
</dict>
</plist>
```

Then load it (this is the manual "install" step — not run by this story):

```bash
launchctl load ~/Library/LaunchAgents/com.rezops.scheduled-briefing.plist
```

To unregister: `launchctl unload ~/Library/LaunchAgents/com.rezops.scheduled-briefing.plist`.

## Checking for missed/failed runs

`ledger_data/_ops.log.md` is the only place a failed scheduled run surfaces
(AD-7: "a failed scheduled run appends an error entry ... rather than
failing silently"). It's a plain, human-readable markdown file — check it
directly, or `tail`/`grep` it as part of your own monitoring:

```bash
tail -n 20 ledger_data/_ops.log.md
```

No entry for a given day does not, by itself, prove the job ran — it proves
either the job ran and succeeded, or the scheduler never invoked it at all
(a separate concern from what this script can detect; see your scheduler's
own logs — `_cron_stdout.log` / the launchd `StandardOutPath` above — to
confirm invocation actually happened).
