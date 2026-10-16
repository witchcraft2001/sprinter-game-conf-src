@echo off
setlocal EnableExtensions
rem IOCHRDY research: ACEX firmware variants for the ISA /WAIT experiments
rem (diagnostics\ISA_IOCHRDY_WAIT.md, section 7).
rem
rem   build_iochrdy.bat                 all variants, K30 and K50
rem   build_iochrdy.bat K30             all variants, K30 only
rem   build_iochrdy.bat K50 A C         variants A and C, K50 only
rem
rem   O - original source (iochrdy\SP2_ACEX_ORIG.TDF), reference build
rem   A - ISA_WAIT = 20, WAIT_OD = "ISA"   long ISA cycle + no active high in ISA cycles
rem   B - ISA_WAIT = 20, WAIT_OD = "OFF"   long ISA cycle only
rem   C - ISA_WAIT = 3,  WAIT_OD = "ISA"   no active high only, cycle almost original
rem
rem Result: iochrdy\out\STREAM_<chip>_<variant>.BIN, <chip>_<variant>.rpt/.log
rem The working copies of K30\ and K50\ are made in iochrdy\w<chip><variant>,
rem the sources and STREAM.BIN in this directory are not touched.

set MAXPLUS=C:\MAXPLUS2\MAXPLUS2.EXE
set ROOT=%~dp0
set BIN=%ROOT%..\..\bin
set OUT=%ROOT%iochrdy\out

set CHIPS=
set VARS=
:args
if "%~1"=="" goto args_done
if /I "%~1"=="K30" (set CHIPS=%CHIPS% K30& goto args_next)
if /I "%~1"=="K50" (set CHIPS=%CHIPS% K50& goto args_next)
if /I "%~1"=="O" (set VARS=%VARS% O& goto args_next)
if /I "%~1"=="A" (set VARS=%VARS% A& goto args_next)
if /I "%~1"=="B" (set VARS=%VARS% B& goto args_next)
if /I "%~1"=="C" (set VARS=%VARS% C& goto args_next)
echo Unknown argument: %1
echo Usage: build_iochrdy.bat [K30] [K50] [O] [A] [B] [C]
exit /b 1
:args_next
shift
goto args
:args_done
if "%CHIPS%"=="" set CHIPS=K30 K50
if "%VARS%"=="" set VARS=O A B C

if not exist "%MAXPLUS%" (echo Not found: %MAXPLUS% & exit /b 1)
where powershell >nul 2>&1 || (echo PowerShell is required to set the parameters & exit /b 1)
if not exist "%OUT%" md "%OUT%"

set FAILED=
for %%c in (%CHIPS%) do for %%v in (%VARS%) do call :build %%c %%v

echo.
echo ==== Summary
for %%c in (%CHIPS%) do for %%v in (%VARS%) do (
	if exist "%OUT%\STREAM_%%c_%%v.BIN" (echo %%c %%v: OK   iochrdy\out\STREAM_%%c_%%v.BIN) else (echo %%c %%v: FAILED, see iochrdy\out\%%c_%%v.log)
)
if defined FAILED exit /b 1
exit /b 0


:build
set CHIP=%1
set VAR=%2
set WORK=%ROOT%iochrdy\w%CHIP%%VAR%
set LOG=%OUT%\%CHIP%_%VAR%.log
echo.
echo ==== ACEX-%CHIP%, variant %VAR%
if exist "%OUT%\STREAM_%CHIP%_%VAR%.BIN" del "%OUT%\STREAM_%CHIP%_%VAR%.BIN"
if exist "%WORK%" rd /s /q "%WORK%"
md "%WORK%"
echo ACEX-%CHIP% variant %VAR% > "%LOG%"
copy "%ROOT%%CHIP%\*.*" "%WORK%\" >> "%LOG%" 2>&1

if /I "%VAR%"=="O" (
	copy /y "%ROOT%iochrdy\SP2_ACEX_ORIG.TDF" "%WORK%\SP2_ACEX.TDF" >> "%LOG%" 2>&1
	echo original SP2_ACEX.TDF
	goto compile
)
if /I "%VAR%"=="A" (set P_WAIT=20& set P_OD=ISA)
if /I "%VAR%"=="B" (set P_WAIT=20& set P_OD=OFF)
if /I "%VAR%"=="C" (set P_WAIT=3& set P_OD=ISA)
powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%iochrdy\setparam.ps1" -Path "%WORK%\SP2_ACEX.TDF" -IsaWait %P_WAIT% -WaitOd %P_OD%
if errorlevel 1 (set FAILED=1& goto :eof)

:compile
pushd "%WORK%"
"%MAXPLUS%" -compile SP2_ACEX >> "%LOG%"
if not exist SP2_ACEX.ttf (
	echo Compilation failed, no SP2_ACEX.ttf
	popd
	set FAILED=1
	goto :eof
)
if /I "%CHIP%"=="K50" (
	"%BIN%\transttf.exe" SP2_ACEX.ttf STREAM50.BIN >> "%LOG%"
	"%BIN%\altera0pak.exe" STREAM50.BIN STREAM.BIN >> "%LOG%"
) else (
	"%BIN%\transttf.exe" SP2_ACEX.ttf STREAM.BIN >> "%LOG%"
)
if not exist STREAM.BIN (
	echo No STREAM.BIN after transttf
	popd
	set FAILED=1
	goto :eof
)
copy /y STREAM.BIN "%OUT%\STREAM_%CHIP%_%VAR%.BIN" >nul
copy /y sp2_acex.rpt "%OUT%\%CHIP%_%VAR%.rpt" >nul
findstr /C:"SP2_ACEX  EP1K" sp2_acex.rpt
findstr /C:"fmax is" sp2_acex.rpt
popd
goto :eof
