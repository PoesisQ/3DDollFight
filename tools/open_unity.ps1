param([string]$EditorPath = $env:DOLLFIGHT_UNITY_EDITOR, [string]$ExecuteMethod, [switch]$D3D12)
$ErrorActionPreference = 'Stop'
$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\unity'))
$version = '6000.3.27f1'
if (-not $EditorPath) {
    $EditorPath = [Environment]::GetEnvironmentVariable('DOLLFIGHT_UNITY_EDITOR', 'User')
}
if (-not $EditorPath) {
    $candidates = @(
        "S:\Unity\Editors\$version\Editor\Unity.exe",
        "$env:ProgramFiles\Unity\Hub\Editor\$version\Editor\Unity.exe"
    )
    $EditorPath = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
}
if (-not $EditorPath -or -not (Test-Path -LiteralPath $EditorPath)) {
    throw "Install Unity $version, or set DOLLFIGHT_UNITY_EDITOR to its Unity.exe path."
}
$scene = Join-Path $projectRoot 'Assets\Scenes\DollFight.unity'
$arguments = @('-projectPath', ('"' + $projectRoot + '"'))
if ($D3D12) { $arguments += '-force-d3d12' }
if ($ExecuteMethod) {
    $arguments += @('-executeMethod', $ExecuteMethod)
} elseif (-not (Test-Path -LiteralPath $scene)) {
    # The menu method creates the scene after imports/compilation and keeps
    # the Editor open. Licensing remains Unity's normal official flow.
    $arguments += @('-executeMethod', 'DollFight.Editor.DemoBuild.CreateScene')
} else {
    $arguments += @('-executeMethod', 'DollFight.Editor.DemoBuild.OpenScene')
}
Start-Process -FilePath $EditorPath -ArgumentList $arguments
