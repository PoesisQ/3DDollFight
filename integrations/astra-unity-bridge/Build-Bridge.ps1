$ErrorActionPreference = 'Stop'
$labEnv = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\lab-env'))
$cmake = Join-Path $labEnv 'cmake\tools\bin\cmake.exe'
$build = Join-Path $PSScriptRoot 'build'
& $cmake -S (Join-Path $PSScriptRoot 'native') -B $build -G 'Visual Studio 16 2019' -A x64 "-DASTRA_ROOT=$labEnv\astra\sdk"
if ($LASTEXITCODE -ne 0) { throw 'Bridge configuration failed.' }
& $cmake --build $build --config Release --parallel 4
if ($LASTEXITCODE -ne 0) { throw 'Bridge build failed.' }
$output = Join-Path $build 'bin\Release'
Get-ChildItem -LiteralPath (Join-Path $labEnv 'astra\sdk\bin') |
    Where-Object { $_.Extension -ne '.exe' } |
    ForEach-Object { Copy-Item -LiteralPath $_.FullName -Destination $output -Recurse -Force }
Write-Host "Bridge ready: $output\AstraUnityBridge.exe"
