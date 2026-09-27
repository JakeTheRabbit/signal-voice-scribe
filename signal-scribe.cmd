@echo off
rem Signal Scribe command line (Windows). Try: signal-scribe --help
"%~dp0.venv\Scripts\python.exe" -m scribe.cli %*
