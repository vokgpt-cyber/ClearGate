@echo off
REM =============================================================================
REM Cleargate - pilot user admin (thin wrapper around the in-container CLI)
REM =============================================================================
REM Run from an elevated PowerShell / cmd on the pilot server. The real tool
REM lives inside the backend container; this file just forwards arguments.
REM
REM Common usage (username is POSITIONAL for most commands):
REM     users.bat list-users
REM     users.bat create-user alice
REM     users.bat create-user alice --inactive
REM     users.bat reset-password alice
REM     users.bat set-active alice               (enables alice)
REM     users.bat set-active alice --inactive    (disables alice)
REM     users.bat delete-user alice --yes
REM     users.bat --help
REM
REM Exception: the `seed` subcommand (used by install.bat) takes --username
REM     users.bat seed --username test1 --password-stdin --if-empty
REM
REM Per-subcommand help:
REM     users.bat create-user --help
REM
REM Notes:
REM   - Passwords are prompted via getpass by default (no echo, no history).
REM   - --password / --password-stdin are available for scripting.
REM   - The users.db lives inside the backend container's volu