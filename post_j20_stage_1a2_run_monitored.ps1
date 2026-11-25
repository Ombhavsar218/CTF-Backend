$ErrorActionPreference = "Continue"
$start = Get-Date
$meta = "post_j20_stage_1a2_broker_full_monitored.meta.txt"
$stdout = "post_j20_stage_1a2_broker_full_monitored.stdout.txt"
$stderr = "post_j20_stage_1a2_broker_full_monitored.stderr.txt"
$exitFile = "post_j20_stage_1a2_broker_full_monitored.exit.txt"
"START=$($start.ToString('o'))" | Set-Content $meta
"CMD=.\venv\Scripts\python.exe -m pytest broker/tests -q" | Add-Content $meta
$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = (Resolve-Path .\venv\Scripts\python.exe).Path
$psi.Arguments = "-m pytest broker/tests -q"
$psi.WorkingDirectory = (Get-Location).Path
$psi.RedirectStandardOutput = $true
$psi.RedirectStandardError = $true
$psi.UseShellExecute = $false
$psi.CreateNoWindow = $true
$p = New-Object System.Diagnostics.Process
$p.StartInfo = $psi
[void]$p.Start()
"PID=$($p.Id)" | Add-Content $meta
$stdoutStream = [System.IO.StreamWriter]::new($stdout, $false, [System.Text.Encoding]::UTF8)
$stderrStream = [System.IO.StreamWriter]::new($stderr, $false, [System.Text.Encoding]::UTF8)
# async read
$outTask = $p.StandardOutput.ReadToEndAsync()
$errTask = $p.StandardError.ReadToEndAsync()
while(-not $p.HasExited){
  Start-Sleep -Seconds 5
}
$stdoutStream.Write($outTask.Result); $stdoutStream.Close()
$stderrStream.Write($errTask.Result); $stderrStream.Close()
$ec = $p.ExitCode
$end = Get-Date
"END=$($end.ToString('o'))" | Add-Content $meta
"EXIT=$ec" | Add-Content $meta
"DURATION_SEC=$([math]::Round(($end-$start).TotalSeconds,3))" | Add-Content $meta
Set-Content $exitFile $ec
Write-Output "DONE_EXIT=$ec"
