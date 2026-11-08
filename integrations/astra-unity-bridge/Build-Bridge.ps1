param([string]$LabEnv = $env:ASTRA_LAB_ENV)
$ErrorActionPreference = 'Stop'
if (-not $LabEnv) { $LabEnv = Join-Path $PSScriptRoot '..\lab-env' }
$LabEnv = [IO.Path]::GetFullPath($LabEnv)
$cmake = Join-Path $LabEnv 'cmake\tools\bin\cmake.exe'
$sdk = Join-Path $LabEnv 'astra\sdk'
if (-not (Test-Path -LiteralPath $cmake) -or -not (Test-Path -LiteralPath (Join-Path $sdk 'include\astra\capi\astra.h'))) {
    throw "Astra lab environment not found at $LabEnv. Set ASTRA_LAB_ENV or pass -LabEnv."
}
$build = Join-Path $PSScriptRoot 'build'
$configureArgs = @('-S', (Join-Path $PSScriptRoot 'native'), '-B', $build,
    '-G', 'Visual Studio 16 2019', '-A', 'x64', "-DASTRA_ROOT=$sdk")
# A locally installed VS2019 may exist even when vswhere has no registered instance.
$vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
$registeredVs = if (Test-Path -LiteralPath $vswhere) { & $vswhere -products '*' -version '[16.0,17.0)' -property installationPath } else { $null }
if (-not $registeredVs -and (Test-Path -LiteralPath 'C:\VS2019\VC\Auxiliary\Build\vcvarsall.bat')) {
    $configureArgs += '-DCMAKE_GENERATOR_INSTANCE=C:/VS2019,version=16.11.60.0'
}
& $cmake @configureArgs
if ($LASTEXITCODE -ne 0) { throw 'Bridge configuration failed.' }
& $cmake --build $build --config Release --parallel 4
if ($LASTEXITCODE -ne 0) { throw 'Bridge build failed.' }
$output = Join-Path $build 'bin\Release'
Get-ChildItem -LiteralPath (Join-Path $sdk 'bin') |
    Where-Object { $_.Extension -ne '.exe' } |
    ForEach-Object { Copy-Item -LiteralPath $_.FullName -Destination $output -Recurse -Force }
Write-Host "Bridge ready: $output\AstraUnityBridge.exe"
