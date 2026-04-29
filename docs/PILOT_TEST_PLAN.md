# Cleargate Pilot Test Plan (for Vadim)

This is your runbook for validating the pilot install on a clean Windows Server VM **before** handing it to the IT team. Goal: surface every gap in a controlled environment, then ship a bulletproof bundle.

## Phase 1 — Set up Hyper-V on your laptop

Your ASUS ROG G14 with Win 11 Pro has Hyper-V built in. One-time setup:

```powershell
# Run in elevated PowerShell on the laptop (not in the VM)
Enable-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V -All
```

Reboot when prompted.

## Phase 2 — Get a Windows Server 2022 VM running

1. Download **Windows Server 2022 Evaluation ISO** (free, 180-day trial):
   https://www.microsoft.com/en-us/evalcenter/evaluate-windows-server-2022
   (~6 GB; pick the "ISO downloads" option, English or Russian.)

2. Create the VM in PowerShell (faster than the Hyper-V Manager wizard):

```powershell
$vmName = "Cleargate-Test"
$vhdPath = "D:\Hyper-V\$vmName\$vmName.vhdx"  # change drive if D: doesn't exist
$isoPath = "C:\Users\V\Downloads\WindowsServer2022.iso"  # adjust to your download

New-VM -Name $vmName -Generation 2 -MemoryStartupBytes 32GB -NewVHDPath $vhdPath -NewVHDSizeBytes 80GB
Set-VMProcessor -VMName $vmName -Count 4 -ExposeVirtualizationExtensions $true
Set-VMFirmware -VMName $vmName -EnableSecureBoot Off
Add-VMDvdDrive -VMName $vmName -Path $isoPath
Set-VMNetworkAdapter -VMName $vmName -Name "Network Adapter"  # uses default switch
Start-VM -Name $vmName
vmconnect.exe localhost $vmName
```

3. Install Windows Server 2022 in the VM (Standard, Desktop Experience). Set an Admin password. ~15 min.

4. After first login inside the VM:
   - Disable IE Enhanced Security so you can browse: Server Manager -> Local Server -> "IE Enhanced Security Configuration" -> Off for Administrators.
   - Set timezone to MSK.

## Phase 3 — Install Docker Desktop in the VM

Inside the VM:

1. Download Docker Desktop for Windows: https://www.docker.com/products/docker-desktop/
2. Run the installer. **Check "Use WSL 2 instead of Hyper-V"** (Windows Server supports WSL2 since 2022).
3. Reboot when asked.
4. Launch Docker Desktop. Wait for the whale icon to stop animating. Confirm `docker version` returns OK in PowerShell.

If WSL2 fails to install, run inside the VM:

```powershell
wsl --install
# reboot, then:
wsl --set-default-version 2
```

## Phase 4 — Build the offline bundle on YOUR DEV BOX

This is done on your ROG G14, not in the VM. You need a working Cleargate install first.

```powershell
# On your dev box, in the Velum repo root:
cd C:\Users\V\Documents\Claude\Projects\Velum

# 1. Bring up Cleargate (you already did this; just confirm)
.\start.bat
.\status.bat   # all 4 should be healthy

# 2. Make sure the model is pulled (probably already done)
docker exec cleargate-ollama ollama pull qwen2.5:7b-instruct-q4_K_M

# 3. Build the offline bundle (takes ~5-10 min, mostly tar of model)
powershell -ExecutionPolicy Bypass -File .\scripts\package-offline.ps1
```

This creates `dist\cleargate-offline-<timestamp>\` with everything the IT team needs (~9 GB).

## Phase 5 — Test the bundle in the VM

1. **Copy the bundle into the VM.** Easiest method: enable file sharing in the VM and copy via SMB. Or use Hyper-V's Enhanced Session Mode (Ctrl+Alt+End -> redirect drives), or mount the bundle folder as a shared folder.

   Fastest one-liner from the host (outside the VM):
   ```powershell
   $vmName = "Cleargate-Test"
   $bundlePath = "C:\Users\V\Documents\Claude\Projects\Velum\dist\cleargate-offline-<timestamp>"
   Copy-VMFile -VMName $vmName -SourcePath $bundlePath -DestinationPath "C:\Cleargate" -CreateFullPath -FileSource Host -Recursive
   ```
   (Requires Hyper-V Integration Services for guest file copy; enabled by default on Server 2022.)

2. **Inside the VM**, navigate to `C:\Cleargate` (or wherever you copied the bundle).

3. **Right-click `offline-install.bat` -> Run as administrator**.

4. Watch what happens. Note every prompt, error, or pause.

5. When done, open `http://localhost` in the VM's Edge browser. You should see the Cleargate login page.

6. Log in with `test1` / `cleargate-pilot`. Try to anonymize a short Russian text.

## Phase 6 — Document gaps and fix

Keep a running log of:
- Anything the script did NOT auto-handle (manual prompt, missing dep, etc.)
- Anything the docs did NOT explain clearly
- Any error message that confused you

Each gap = either a script fix or a doc clarification. After a clean second-pass install, the bundle is ready to ship.

## Phase 7 — Hand off to IT

Send the IT team:
1. The bundled folder (or its ZIP) — ~9 GB
2. `INSTALL_README.md` (English) and `INSTALL_README_RU.md` (Russian)
3. A "first install" Teams call invite — sit on screen-share for the first run

That's it. No surprises.

---

## Known dev-box port conflicts (NOT a problem on IT's clean VM)

Your ROG G14 runs both VERITAS and Cleargate. They both publish on ports 11434 (ollama) and 8000 (backend). When switching between them:

```powershell
# Before starting Cleargate:
docker stop epam-meet-ollama epam-meet-whisper 2>$null

# Before starting VERITAS:
cd C:\Users\V\Documents\Claude\Projects\Velum
.\stop.bat
```

The IT team's server will never see this because it hosts only Cleargate. Don't bake VERITAS-specific stops into the pilot scripts.

Longer-term fix (post-pilot): remap VERITAS to ports 11435/8001, or unify on one shared ollama container.

---

## Quick reference — preflight + offline install commands

For the IT team, the entire install is two commands plus one click:

```powershell
# 1. Install Docker Desktop, reboot, launch it.
# 2. Right-click offline-install.bat -> Run as administrator.
# 3. (Optional) re-run preflight any time:
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\preflight.ps1
```
