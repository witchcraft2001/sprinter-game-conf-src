# Sets ISA_WAIT, WAIT_OD and ISA_CLK_FIX in the PARAMETERS header of SP2_ACEX.TDF.
# Each parameter must be replaced exactly once, otherwise exit code 1.
param([string]$Path, [int]$IsaWait, [string]$WaitOd, [int]$ClkFix)

$enc = [Text.Encoding]::GetEncoding(28591)
$text = [IO.File]::ReadAllText($Path, $enc)

$reW = New-Object Text.RegularExpressions.Regex('(?m)^([ \t]*ISA_WAIT[ \t]*=[ \t]*)[0-9]+')
$reO = New-Object Text.RegularExpressions.Regex('(?m)^([ \t]*WAIT_OD[ \t]*=[ \t]*)"[A-Z]+"')
if ($reW.Matches($text).Count -ne 1) { Write-Host "setparam: ISA_WAIT not found once in $Path"; exit 1 }
if ($reO.Matches($text).Count -ne 1) { Write-Host "setparam: WAIT_OD not found once in $Path"; exit 1 }
$reF = New-Object Text.RegularExpressions.Regex('(?m)^([ \t]*ISA_CLK_FIX[ \t]*=[ \t]*)[01]')
if ($reF.Matches($text).Count -ne 1) { Write-Host "setparam: ISA_CLK_FIX not found once in $Path"; exit 1 }

$text = $reW.Replace($text, '${1}' + $IsaWait)
$text = $reO.Replace($text, '${1}"' + $WaitOd + '"')
$text = $reF.Replace($text, '${1}' + $ClkFix)
[IO.File]::WriteAllText($Path, $text, $enc)
Write-Host "setparam: ISA_WAIT = $IsaWait, WAIT_OD = `"$WaitOd`", ISA_CLK_FIX = $ClkFix"
exit 0
