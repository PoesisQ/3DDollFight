param([string]$UnityEditor = 'D:\unity\Unity Hub\6000.3.10f1\Editor\Unity.exe', [switch]$WithGraphics, [switch]$Dual)
$ErrorActionPreference = 'Stop'
if (-not (Test-Path -LiteralPath $UnityEditor)) { throw 'Unity Editor not found.' }
if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'build\bin\Release\AstraUnityBridge.exe'))) { throw 'Run Build-Bridge.cmd first.' }
New-Item -ItemType Directory -Path (Join-Path $PSScriptRoot 'logs') -Force | Out-Null
# Some automation environments omit ALLUSERSPROFILE. Supply its normal Windows value for this process only.
if (-not [Environment]::GetEnvironmentVariable('ALLUSERSPROFILE')) {
    [Environment]::SetEnvironmentVariable('ALLUSERSPROFILE', [Environment]::GetEnvironmentVariable('ProgramData'), 'Process')
}
$project = Join-Path $PSScriptRoot 'UnityProject'
$testName = if ($Dual) { 'unity-dual-self-test' } else { 'unity-self-test' }
$method = if ($Dual) { 'AstraUnity.Editor.AstraDualSelfTest.Run' } else { 'AstraUnity.Editor.AstraBridgeSelfTest.Run' }
$log = Join-Path $PSScriptRoot "logs\$testName.log"
$result = Join-Path $PSScriptRoot "logs\$testName.json"
if (Test-Path -LiteralPath $result) { Remove-Item -LiteralPath $result -Force }
$arguments = @('-batchmode', '-projectPath', ('"' + $project + '"'),
    '-executeMethod', $method, '-logFile', ('"' + $log + '"'))
if (-not $WithGraphics) { $arguments += '-nographics' }
$process = Start-Process -FilePath $UnityEditor -ArgumentList $arguments -PassThru -WindowStyle Hidden
if (-not $process.WaitForExit(180000)) {
    Stop-Process -Id $process.Id -Force
    throw 'Unity test timed out. See logs/unity-self-test.log.'
}
if ($process.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $result)) { throw 'Unity test failed. See logs/unity-self-test.log.' }
$report = Get-Content -LiteralPath $result -Raw | ConvertFrom-Json
if (-not $report.passed) { throw $report.error }
Write-Host "PASS: $($report.checks.Count) checks. Report: $result"
