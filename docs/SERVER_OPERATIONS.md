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
