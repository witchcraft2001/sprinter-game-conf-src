@echo off
setlocal EnableExtensions DisableDelayedExpansion
if /i "%~1"=="GAME_K50" goto variant_ok
if /i "%~1"=="STANDARD_K50" goto variant_ok
echo Usage: build_k50.cmd GAME_K50 or STANDARD_K50
exit /b 2
:variant_ok
set "VARIANT=%~1"
set "ROOT=%~dp0..\.."
if defined MAXPLUS2_EXE goto compiler_selected
set "MAXPLUS2_EXE=C:\MAXPLUS2\MAXPLUS2\MAXPLUS2.EXE"
if not exist "%MAXPLUS2_EXE%" set "MAXPLUS2_EXE=C:\MAXPLUS2\MAXPLUS2.EXE"
:compiler_selected
if not exist "%MAXPLUS2_EXE%" (
  echo MAXPLUS2_EXE not found: %MAXPLUS2_EXE%
  exit /b 1
)
set "WORK=%~dp0build\%VARIANT%-%RANDOM%-%RANDOM%"
cscript.exe //nologo "%ROOT%\tools\k50_build.js" Prepare "%WORK%" "%VARIANT%"
if errorlevel 1 exit /b 1
pushd "%WORK%"
if errorlevel 1 exit /b 1
echo Compiling %VARIANT% in %CD%
"%MAXPLUS2_EXE%" -compile SP2_ACEX > compile.log 2>&1
if errorlevel 1 goto failed
if not exist SP2_ACEX.sof goto failed
if not exist SP2_ACEX.ttf goto failed
if not exist SP2_ACEX.rpt goto failed
"%ROOT%\bin\transttf.exe" SP2_ACEX.ttf STREAM50.BIN >> compile.log 2>&1
if errorlevel 1 goto failed
"%ROOT%\bin\Altera0pak.exe" STREAM50.BIN K50.packed >> compile.log 2>&1
if errorlevel 1 goto failed
"%ROOT%\bin\Altera0pak.exe" -d K50.packed roundtrip.bin >> compile.log 2>&1
if errorlevel 1 goto failed
cscript.exe //nologo "%ROOT%\tools\k50_build.js" Verify "%WORK%" "%VARIANT%" >> compile.log 2>&1
if errorlevel 1 goto failed
if /i "%~2"=="EXPORT_STREAM" (
  cscript.exe //nologo "%ROOT%\tools\k50_build.js" PublishStandard "%WORK%" "%VARIANT%" >> compile.log 2>&1
  if errorlevel 1 goto failed
)
certutil -hashfile K50.ACX SHA256 > acx-sha256.txt 2>&1
echo Packaging passed: %WORK%\K50.ACX
echo Review fitting and CLK42/derived clock timing in SP2_ACEX.rpt before board testing.
popd
exit /b 0
:failed
echo FAILED. Diagnostics retained in %WORK%
popd
exit /b 1
