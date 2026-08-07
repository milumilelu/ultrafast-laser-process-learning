$ErrorActionPreference = 'Stop'
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$memoryRoot = (Resolve-Path (Join-Path $scriptRoot '..\..\..')).Path
$venvPy = Join-Path $memoryRoot '.venv\Scripts\python.exe'
$env:PYTHONUTF8 = '1'
$env:PYTHONPATH = Join-Path $memoryRoot 'src'
$prep = Join-Path $scriptRoot 'prepare_annotations.py'
$workDir = Join-Path $scriptRoot '..\work'
New-Item -ItemType Directory -Path $workDir -Force | Out-Null
$log = Join-Path $workDir ("prepare_annotations_" + (Get-Date -Format 'yyyyMMdd_HHmmss') + ".log")
if ($args.Count -gt 0) {
    & $venvPy $prep @args *> $log
} else {
    & $venvPy $prep --per-scenario 3 *> $log
}
exit $LASTEXITCODE
