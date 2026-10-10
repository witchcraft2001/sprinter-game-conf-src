@echo off
@echo off
set BIN=..\..\bin\
set LOG=compile.log
for /F %%i in ('date /t') do set mydate=%%i
for /F %%i in ('time /t') do set mytime=%%i
set mydt=%mydate% %mytime%

set CHIP=7128

echo 0. [2/2] ALTERA MAX-DX-%CHIP% STREAM
echo %mydt%: [2/2] ALTERA MAX-DX-%CHIP% STREAM > %LOG%

rem if exist SP2_MAX_DX_%CHIP%.pof goto quit

copy %CHIP%\*.ACF .\*.* >> %LOG% 2>&1

C:\MAXPLUS2\MAXPLUS2.EXE -compile SP2_MAX_DX >> %LOG%

del *.txt >> %LOG% 2>&1
del *.bak >> %LOG% 2>&1
del *.cnf >> %LOG% 2>&1
del *.db? >> %LOG% 2>&1

del *.hif >> %LOG% 2>&1
del *.mmf >> %LOG% 2>&1
del *.mtf >> %LOG% 2>&1
del *.mtb >> %LOG% 2>&1
del *.hex >> %LOG% 2>&1
del *.ndb >> %LOG% 2>&1
del *.pin >> %LOG% 2>&1
rem del *.pof >> %LOG% 2>&1
del *.snf >> %LOG% 2>&1
del *.fit >> %LOG% 2>&1
del *.jam >> %LOG% 2>&1
del *.jbc >> %LOG% 2>&1

del *.SCF >> %LOG% 2>&1
del *.ACF >> %LOG% 2>&1
rem del *.TDF >> %LOG% 2>&1
del *.INC >> %LOG% 2>&1
del *.MIF >> %LOG% 2>&1

ren SP2_MAX_DX.pof SP2_MAX_DX_%CHIP%.pof >> %LOG% 2>&1

:quit
