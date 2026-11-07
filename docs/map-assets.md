# 地图资源恢复

`menuscene` 保留三个对战场景、选角/选场菜单、角色资产和地下竞技场预览图。**Saint Maurice / Cloud 的扫描及其两张预览图不随 Git 或 LFS 下载**，需要另行取回；目前没有已发布的资源包下载地址。对应目录内已保留 README，可直接按文件名放回。

## 离线恢复包

地图转换产物分为两个独立 ZIP，包内保留相对仓库根目录的路径，顶层包含 `unity/Assets/`，无需原始 SOG / PLY 或再次转换。

| 文件名 | 内容 | 什么时候需要 |
| --- | --- | --- |
| `DollFight-maps-runtime-v1.zip` | 教堂和 Cloud 对战扫描、两张选场预览图、对应 `.meta`、来源和转换记录 | 恢复正常选场和三场地对战 |
| `DollFight-maps-full-preview-v1.zip` | 完整教堂扫描及 `.meta` | 可选；仅完整勘景场景需要 |

制作机器上的本地交付目录为 `outputs/map-packages/2026-11-07-menuscene-v1/`，与源码分开交付，不会随 Git 克隆下载。交付目录中的 `SHA256SUMS.txt` 可核对两个 ZIP，`restore-verification.json` 记录针对对应源码提交的恢复验证结果。每个 ZIP 内的 `outputs/map-packages/*-package-manifest.json` 另记逐文件大小和 SHA-256。

先克隆 `menuscene` 并准备角色与动作；然后在仓库根目录解压收到的主包，完整勘景包按需解压到同一位置。下面的 `D:\收到的地图包` 替换为实际存放 ZIP 的目录：

```powershell
Expand-Archive -LiteralPath 'D:\收到的地图包\DollFight-maps-runtime-v1.zip' -DestinationPath . -Force
# 可选，恢复完整教堂勘景：
Expand-Archive -LiteralPath 'D:\收到的地图包\DollFight-maps-full-preview-v1.zip' -DestinationPath . -Force
```

解压后应直接出现下表中的文件，避免多套一层 ZIP 文件名目录。包内的恢复说明和包清单放在被忽略的 `outputs/map-packages/` 下；不会改变现有场景布局或资源 GUID。只恢复主包时，下面的校验命令应有四项 `OK`，完整勘景一项 `MISSING`；两包都恢复后应为五项 `OK`。

## 需要取回的文件

以下路径均相对仓库根目录。字节数和完整 SHA-256 以 [`restore-manifest.json`](../data/environments/restore-manifest.json) 为校验清单；清单中的 `assets` 是转换产物，`sources` 是仅重新转换时才需要的原件。

| 放置位置（相对仓库根目录） | 大小（bytes） | 用途 |
| --- | ---: | --- |
| `unity/Assets/StreamingAssets/Environments/SaintMaurice/church.spz` | 90,546,209 | 教堂对战扫描 |
| `unity/Assets/StreamingAssets/Environments/Cloud/cloud.spz` | 10,260,154 | Cloud 对战扫描 |
| `unity/Assets/LocalScenes/SaintMaurice/church-full.spz` | 193,594,635 | 完整教堂勘景扫描；仅 SaintMauricePreview 场景需要 |
| `unity/Assets/Resources/DollFight/Selection/Stages/saint-maurice.png` | 1,466,334 | 教堂选场预览图；缺失时显示占位 |
| `unity/Assets/Resources/DollFight/Selection/Stages/cloud.png` | 1,360,143 | Cloud 选场预览图；缺失时显示占位 |

`church.spz` 和 `cloud.spz` 各自对应一张对战地图；不需要同时恢复另一张地图才能使用其中一张。`church-full.spz` 仅用于 `Assets/Scenes/SaintMauricePreview.unity` 完整勘景，不是教堂对战或普通构建的必需文件。两张 PNG 只影响选场预览，缺失时菜单显示占位；地下竞技场 `underground.png` 已随仓库的 LFS 提交。

Unity `.unity` 场景中已保存扫描路径。**恢复时保留文件名和大小写，放回已有目录即可，不要重新 Create 场景。** 如果资源包还包含对应 `.meta`、`provenance.json` 或教堂 `ATTRIBUTION.txt`，保留原有目录结构一起恢复；这些本地文件继续被忽略。仓库中的来源配置与本清单仍然保留。

## 恢复后启动

1. 在仓库根目录准备角色和动作：

   ```powershell
   git lfs pull
   uv sync --locked
   uv run --locked python tools/prepare_unity.py
   ```

2. 资源包若以 `unity/Assets/...` 为顶层结构，在仓库根目录解压；若收到的是单独文件，按上表逐个放回。只提供转换产物时，不需要原始 SOG / PLY、Node.js 或 npm。
3. 使用下方命令核对文件大小和 SHA-256。
4. 双击 `Start-Unity.cmd` 打开工程，在已有场景中选择已恢复的场地；也可以从 Unity 打开 `Assets/Scenes/SaintMauriceDuel.unity` / `CloudDuel.unity`。扫描渲染要求 Direct3D 12，相关说明见[教堂场景说明](saint-maurice-scene.md)。

项目已将 Windows 图形 API 固定为 Direct3D 12。若需显式指定，在完成角色和动作准备后从仓库根目录运行：

```powershell
powershell -NoProfile -File tools/open_unity.ps1 -D3D12
```

`Start-SaintMaurice.cmd` 会运行 `prepare_saint_maurice.py`，即使已放回 SPZ 也会先读取原始 SOG；**只有转换产物时使用 `Start-Unity.cmd`，不要用这个要求原件的入口。** 这些步骤不生成 Windows 独立程序；`Play-DollFight-Unity.cmd` / `Play-SaintMaurice.cmd` 需要另行构建的本机程序。

未恢复扫描时，先使用地下竞技场。教堂与 Cloud 的场景条目仍会出现，但缺少地图数据；它们不是已经随克隆完整恢复的场地。恢复地图/预览图或更新规则、动作后，通过 **DollFight → Build Windows Demo** 重新构建，`outputs/arcade-select/` 中的独立程序才会更新。构建三个场地前应准备两份运行扫描；完整教堂勘景扫描可不放入运行包。

## 校验文件

在仓库根目录运行。`OK` 表示内容与本次清单一致，`MISSING` 表示尚未恢复，`MISMATCH` 表示文件大小或内容不同。可选预览和勘景文件尚未恢复时同样显示 `MISSING`，不代表已经恢复的对战扫描无效。

```powershell
$manifest = Get-Content -LiteralPath data/environments/restore-manifest.json -Raw | ConvertFrom-Json
$results = foreach ($asset in $manifest.assets) {
    if (-not (Test-Path -LiteralPath $asset.path -PathType Leaf)) {
        [pscustomobject]@{ Status = 'MISSING'; Path = $asset.path }
        continue
    }
    $file = Get-Item -LiteralPath $asset.path
    $hash = (Get-FileHash -LiteralPath $asset.path -Algorithm SHA256).Hash
    $status = if ($file.Length -eq $asset.bytes -and $hash -eq $asset.sha256) { 'OK' } else { 'MISMATCH' }
    [pscustomobject]@{ Status = $status; Path = $asset.path }
}
$results | Format-Table -AutoSize
```

也可以单独校验，例如：

```powershell
Get-FileHash -LiteralPath unity/Assets/StreamingAssets/Environments/Cloud/cloud.spz -Algorithm SHA256
```

## 只有原始扫描时重建

原件默认放在仓库上一级：`../Parish Church of Saint Maurice.sog`、`../cloud.ply`。原件哈希分别保存在 [`saint-maurice.json`](../data/environments/saint-maurice.json) 和 [`cloud.json`](../data/environments/cloud.json)，恢复清单的 `sources` 也记录了同一 SHA-256。也可将原件放在其他位置并通过 `--source` 指定。

```powershell
# 先完成角色和动作准备，然后按需要重建对应地图
uv run --locked python tools/prepare_saint_maurice.py --source '..\Parish Church of Saint Maurice.sog'
uv run --locked python tools/prepare_cloud.py --source '..\cloud.ply'
```

重建需要 Node.js 22+ 和 npm，脚本使用已锁定的 splat-transform 3.10.3。重建扫描不会自动恢复菜单 PNG；预览图可单独取回，或按[街机选择说明](arcade-selection.md)从原生场景重新捕获。已有场景直接打开即可，只有要重新生成场景布局时才使用 Create 菜单。

## 本次上传范围

教堂和 Cloud 的扫描、相关预览图及本机构建保持本地，不在本次分支中上传，也不发布到 Release。教堂来源与署名记录见 [`saint-maurice.json`](../data/environments/saint-maurice.json)，Cloud 来源记录见 [`cloud.json`](../data/environments/cloud.json)。后续素材包单独管理，取回时按本清单恢复；不要将其误加入 Git。
