# Auto-start on Windows (venue PC)

Make the print worker start automatically and stay running, so nobody has to open
a terminal.

## One-time setup

1. Install Python 3.11+ and create the venv (from the project folder):
   ```
   python -m venv .venv
   .venv\Scripts\python -m pip install -r requirements.txt
   ```
2. Copy `.env.example` to `.env` and fill it in.

## Register the auto-start task

Open **Command Prompt as Administrator**, then (adjust the path):

```
schtasks /Create /TN RowRunnerPrint /SC ONLOGON /RL HIGHEST /F ^
  /TR "C:\path\to\rowrunner-print\deploy\run-worker.bat"
```

This runs the worker at every logon. `run-worker.bat` appends output to `worker.log`.

### Make it restart if it crashes / run headless
In **Task Scheduler** (taskschd.msc) open the **RowRunnerPrint** task and set:
- **General → Run whether user is logged on or not**
- **Settings → If the task fails, restart every: 1 minute**, up to 3 times
- **Settings → If the running task does not end when requested, force it to stop**

## Managing it
- **Start now:** `schtasks /Run /TN RowRunnerPrint`
- **Stop:** `schtasks /End /TN RowRunnerPrint`
- **Remove:** `schtasks /Delete /TN RowRunnerPrint /F`
- **Logs:** open `worker.log` in the project folder.

The worker auto-discovers the printer on the LAN, so you don't need to hardcode its
IP — but a DHCP reservation for the printer is still recommended for a permanent setup.
