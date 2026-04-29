# Cleargate - Pilot Installation Guide (Offline)

This bundle installs Cleargate on a pilot server **without requiring internet access** (beyond Docker itself, which must be installed separately).

## Server requirements

- **Windows Server 2019 / 2022** (64-bit)
- **32 GB RAM** minimum (16 GB will work but the model is slow)
- **4+ CPU cores**
- **25 GB free disk space** on the system drive
- **Administrator privileges** (to open firewall and run Docker)
- **Docker Desktop for Windows Server** installed and running
  (Download: https://docs.docker.com/desktop/install/windows-install/)

## Installation (5 steps)

1. Copy this entire folder to the target server (e.g. `C:\Cleargate\`).
2. Install Docker Desktop if not already present. Launch it and wait for the whale icon to stop animating.
3. Right-click `offline-install.bat` -> **Run as administrator**.
4. Wait ~5 minutes for images to load and containers to start.
5. Open `http://<server-ip>` in a browser (or `http://localhost` on the server itself).

### First-time login

Two users are seeded automatically:
- **test1** / password: `cleargate-pilot`
- **test2** / password: `cleargate-pilot`

**IMPORTANT: change these passwords before giving access to real users.**

```
users.bat reset-password test1
users.bat reset-password test2
```

## Daily operations

| Task                      | Command           |
|---------------------------|-------------------|
| Start the stack           | `start.bat`       |
| Stop the stack            | `stop.bat`        |
| Check container health    | `status.bat`      |
| Tail logs                 | `logs.bat`        |
| Manage users              | `users.bat ...`   |
| Re-run installer          | `offline-install.bat` (safe to repeat) |

## Troubleshooting

**Preflight fails with "Port X is held by..."**: another app is using one of 80/3000/8000/11434. Stop that app (often native Ollama or another web server) and re-run.

**Docker daemon not running**: start Docker Desktop from the Start menu, wait for the tray icon to stabilize, re-run.

**"Failed to fetch" in the browser**: the frontend baked a wrong URL. Re-run `offline-install.bat` -- it regenerates the frontend with the correct server IP.

**Model takes too long (> 5 min per request)**: the server has less RAM than recommended. Check with `Get-CimInstance Win32_ComputerSystem | Select TotalPhysicalMemory`.

## Support

Contact the Cleargate dev team with the output of `status.bat` and the last 100 lines of `logs.bat`.
