@echo off
rem Legacy BIOS entry: fresh standard K50, then validated zero-packed STREAM.BIN.
call "%~dp0build_k50.cmd" STANDARD_K50 EXPORT_STREAM
exit /b %errorlevel%
