# RareIQ server operations

RareIQ includes a single-instance local server controller. It stores process
provenance and logs under the configured `log_path`, waits for the boot API
before reporting success, and refuses to stop a process whose session does not
match its managed state.

```powershell
.\.venv\Scripts\python.exe -B tools\server_control.py start
.\.venv\Scripts\python.exe -B tools\server_control.py status
.\.venv\Scripts\python.exe -B tools\server_control.py restart
.\.venv\Scripts\python.exe -B tools\server_control.py stop
.\.venv\Scripts\python.exe -B tools\server_control.py ensure
```

`start.bat` installs the pinned runtime requirements and then uses the same
controller. The server stays running after the launcher window closes.

Development ports are explicit and remain loopback-only:

```powershell
.\.venv\Scripts\python.exe -B tools\server_control.py start --port 9040
```

The controller will not automatically kill an unmanaged process or a process
whose server-session identity differs from the recorded state. Use `--force`
only for an unhealthy process that still has matching managed PID provenance.
Standard logs and the atomic state file are written beneath
`<log_path>\server`.

## Start at login and recover after a crash

Review the plan, then install an immediate current-user logon start and a
five-minute health watchdog. The logon entry uses `pythonw.exe` so it does not
open a console window; the watchdog uses Windows Task Scheduler.

```powershell
.\.venv\Scripts\python.exe -B tools\server_control.py schedule --interval 5
.\.venv\Scripts\python.exe -B tools\server_control.py schedule --interval 5 --apply
```

Both triggers call the idempotent `ensure` command. Concurrent invocations
are serialized by an operating-system file lock. A stopped or stale managed
instance is started using its last loopback host and port. A running instance
is left untouched. Unhealthy, conflicting, or unmanaged processes require
operator review and are never killed or replaced automatically.
If watchdog installation fails, the newly written logon entry is removed
automatically.
