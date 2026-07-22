@echo off
REM Launch the RowRunner print worker on Windows (used by the Task Scheduler entry).
cd /d "%~dp0.."
".venv\Scripts\python.exe" worker.py >> worker.log 2>&1
