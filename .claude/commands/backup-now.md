# /backup-now

Quickly create a backup of the current VELUM project state.

## What this does

1. Runs `git status` to verify there are no untracked sensitive files
2. Runs `git fsck` to verify repository integrity
3. Executes `.\scripts\backup.ps1` with default settings
4. Reports the backup location and size

## Usage

In Claude Code, type:
```
/backup-now
```

Or with options:
```
/backup-now --encrypt
/backup-now --destination "E:\Backups\VELUM"
```

## Implementation

```bash
# Pre-flight checks
git status --porcelain
git fsck --no-progress

# Run backup script
pwsh -File ./scripts/backup.ps1 -Destination "D:\Backups\VELUM"

# Show result
ls -la "D:/Backups/VELUM/daily/" | tail -5
```
