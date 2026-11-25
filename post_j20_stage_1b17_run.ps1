param(
    [Parameter(Mandatory=$true)][string]$Label,
    [Parameter(Mandatory=$true)][string[]]$PytestArgs
)

$ErrorActionPreference = 'Continue'
$evidenceDir = Join-Path $PSScriptRoot 'docs\evidence\post_j20_stage_1b17'
if (-not (Test-Path $evidenceDir)) { New-Item -ItemType Directory -Path $evidenceDir -Force | Out-Null }

$stdoutPath = Join-Path $evidenceDir "$Label.stdout.txt"
$stderrPath = Join-Path $evidenceDir "$Label.stderr.txt"
$exitPath   = Join-Path $evidenceDir "$Label.exit.txt"
$metaPath   = Join-Path $evidenceDir "$Label.meta.txt"

$python = Join-Path $PSScriptRoot 'venv\Scripts\python.exe'
$argList = @('-m', 'pytest') + $PytestArgs
$command = "$python " + ($argList -join ' ')

$sw = [System.Diagnostics.Stopwatch]::StartNew()
$proc = Start-Process -FilePath $python -ArgumentList $argList -WorkingDirectory $PSScriptRoot -NoNewWindow -Wait -PassThru -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath
$sw.Stop()

Set-Content -Path $exitPath -Value ("EXIT=" + $proc.ExitCode)
Set-Content -Path $metaPath -Value @(
    "COMMAND=$command"
    "WORKDIR=$PSScriptRoot"
    "STARTED=$($sw.Elapsed.ToString())"
    "DURATION_SECONDS=$([math]::Round($sw.Elapsed.TotalSeconds, 2))"
    "EXIT=$($proc.ExitCode)"
)

Write-Output "$Label EXIT=$($proc.ExitCode) DURATION=$([math]::Round($sw.Elapsed.TotalSeconds, 2))s"
