param(
    [Parameter(Mandatory=$true)][string]$Label,
    [Parameter(Mandatory=$true)][string]$Exe,
    [Parameter(Mandatory=$true)][string[]]$CmdArgs
)

$ErrorActionPreference = 'Continue'
$evidenceDir = Join-Path $PSScriptRoot 'docs\evidence\post_j20_stage_1b17'
if (-not (Test-Path $evidenceDir)) { New-Item -ItemType Directory -Path $evidenceDir -Force | Out-Null }

$stdoutPath = Join-Path $evidenceDir "$Label.stdout.txt"
$stderrPath = Join-Path $evidenceDir "$Label.stderr.txt"
$exitPath   = Join-Path $evidenceDir "$Label.exit.txt"
$metaPath   = Join-Path $evidenceDir "$Label.meta.txt"

$command = "$Exe " + ($CmdArgs -join ' ')
$sw = [System.Diagnostics.Stopwatch]::StartNew()
$proc = Start-Process -FilePath $Exe -ArgumentList $CmdArgs -WorkingDirectory $PSScriptRoot -NoNewWindow -Wait -PassThru -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath
$sw.Stop()

Set-Content -Path $exitPath -Value ("EXIT=" + $proc.ExitCode)
Set-Content -Path $metaPath -Value @(
    "COMMAND=$command"
    "WORKDIR=$PSScriptRoot"
    "DURATION_SECONDS=$([math]::Round($sw.Elapsed.TotalSeconds, 2))"
    "EXIT=$($proc.ExitCode)"
)

Write-Output "$Label EXIT=$($proc.ExitCode) DURATION=$([math]::Round($sw.Elapsed.TotalSeconds, 2))s"
