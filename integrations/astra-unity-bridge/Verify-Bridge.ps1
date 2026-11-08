param([string]$UnityEditor = $env:DOLLFIGHT_UNITY_EDITOR, [switch]$WithGraphics)
$ErrorActionPreference = 'Stop'
if (-not $UnityEditor) { $UnityEditor = 'D:\unity\Unity Hub\6000.3.27f1\Unity.exe' }
if (-not (Test-Path -LiteralPath $UnityEditor)) { throw 'Unity Editor not found; pass -UnityEditor or set DOLLFIGHT_UNITY_EDITOR.' }
if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'build\bin\Release\AstraUnityBridge.exe'))) { throw 'Build the bridge first.' }
if (-not [Environment]::GetEnvironmentVariable('ALLUSERSPROFILE')) {
    [Environment]::SetEnvironmentVariable('ALLUSERSPROFILE', [Environment]::GetEnvironmentVariable('ProgramData'), 'Process')
}
$project = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..\unity'))
$logDir = Join-Path $PSScriptRoot 'logs'
New-Item -ItemType Directory -Path $logDir -Force | Out-Null
$log = Join-Path $logDir 'unity-game-dual-test.log'
$result = Join-Path $logDir 'unity-dual-self-test.json'
if (Test-Path -LiteralPath $result) { Remove-Item -LiteralPath $result -Force }
$argsList = @('-batchmode','-projectPath',('"' + $project + '"'),'-executeMethod',
    'AstraUnity.Editor.AstraDualSelfTest.Run','-logFile',('"' + $log + '"'))
if (-not $WithGraphics) { $argsList += '-nographics' }
$process = Start-Process -FilePath $UnityEditor -ArgumentList $argsList -PassThru -WindowStyle Hidden
if (-not $process.WaitForExit(180000)) { Stop-Process -Id $process.Id -Force; throw "Unity test timed out. See $log" }
if ($process.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $result)) { throw "Unity test failed. See $log" }
$report = Get-Content -LiteralPath $result -Raw | ConvertFrom-Json
if (-not $report.passed) { throw $report.error }
Write-Host "PASS: $($report.checks.Count) checks."
