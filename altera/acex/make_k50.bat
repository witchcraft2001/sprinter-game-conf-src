@echo off
set BIN=..\..\bin\
set LOG=compile.log
for /F %%i in ('date /t') do set mydate=%%i
for /F %%i in ('time /t') do set mytime=%%i
set mydt=%mydate% %mytime%

set CHIP=K50

echo 0. [1/2] ALTERA ACEX-%CHIP% STREAM
echo %mydt%: [1/2] ALTERA ACEX-%CHIP% STREAM > %LOG%

if exist SP2_ACEX.ttf goto trans

copy %CHIP%\*.* .\*.* >> %LOG% 2>&1

C:\MAXPLUS2\MAXPLUS2.EXE -compile SP2_ACEX >> %LOG%

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
del *.pof >> %LOG% 2>&1
del *.snf >> %LOG% 2>&1
del *.fit >> %LOG% 2>&1

del *.SCF >> %LOG% 2>&1
del *.ACF >> %LOG% 2>&1
del *.TDF >> %LOG% 2>&1
del *.INC >> %LOG% 2>&1
del *.MIF >> %LOG% 2>&1

:trans
%BIN%\transttf.exe SP2_ACEX.ttf STREAM50.BIN >> %LOG%
%BIN%\altera0pak.exe STREAM50.BIN STREAM.BIN
echo on
@type sp2_acex.rpt | grep "fmax is"
