@echo off
rem Mind_Vault daily autopilot launcher (used by Windows Task Scheduler).
rem Runs from the project folder with the isolated .venv; output is appended
rem to logs\autopilot.log. See docs\AUTOPILOT.md.
cd /d "%~dp0"
if not exist logs mkdir logs
".venv\Scripts\python.exe" -m scripts.autopilot %* >> "logs\autopilot.log" 2>&1
