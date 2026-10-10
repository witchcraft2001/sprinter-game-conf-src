@echo off
rem Compatibility entry: always compile a fresh standard K50.
call "%~dp0make_standard_k50.bat"
exit /b %errorlevel%
