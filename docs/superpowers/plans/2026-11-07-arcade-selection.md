# Arcade selection and cloud stage implementation plan

**Goal:** Deliver polished SF6-inspired character and stage selection in the existing native Unity game, import the supplied cloud.ply as stage 03, and visually verify fighters are grounded on its platform.

**Architecture:** Keep the existing four-character catalog, Humanoid replay and damage timeline. A standalone selection overlay owns draft choices and portrait presentation; DollFightDemo applies valid choices and loads a catalogued stage. The environments package owns scan import and platform alignment. Work in the current working tree to retain the user's extensive uncommitted scene, asset and combat work.

**Tech stack:** Unity 6000.3.27f1, Built-in pipeline, C#, local GaussianSplatting renderer, existing pinned splat-transform CLI.

## Visual direction

Full-canvas street tournament poster: dark violet concrete, off-white oversized condensed italic typography, restrained paint strokes, magenta P1 and cyan P2. Character models are the dominant visuals, with a readable central four-person roster. Stage selection uses a large actual scene preview and a three-stage image strip. Short entrance, selection and confirmation transitions reinforce focus. Chinese functional labels remain concise. No Capcom logos or character assets are copied.

## Interfaces and ownership

- UI worker: new `DuelSelectionScreen.cs`, `SelectionPortraits.cs` if useful, `StageCatalog.cs`, own supporting assets. `DuelSelectionScreen.Initialize(DollFightDemo)`, `IsOpen`, `ShowCharacters()`, `ShowStages()`, `Hide()`; caller adds this MonoBehaviour. Confirmation invokes `demo.StartMatch(p1Id, p2Id, stageId)`. Public review affordances may be added and communicated.
- `StageCatalog.All` exposes three stage definitions with `id`, `displayName`, `subtitle`, `sceneName`, `previewResource`. IDs/names: `underground` / `DollFight`, `saint-maurice` / `SaintMauriceDuel`, `cloud` / `CloudDuel`. `StageCatalog.Get(string)` validates IDs. Preview Resources paths: `DollFight/Selection/Stages/underground`, `saint-maurice`, `cloud`.
- Environment worker: `tools/prepare_cloud.py`, `data/environments/cloud.json`, `CloudEnvironment.cs`, `CloudScene.cs`, CloudDuel scene and local converted data. Real scan platform surface maps to world Y=0, combat roots and motion stay unchanged. No edits to Demo or UI.
- Integration worker: `DollFightDemo.cs`, `DuelHud.cs`, existing build entry points and launcher configuration, narrow stage/selection verification and quick native review support. No edits to new UI or cloud environment files. All three scenes enter the standalone build. Normal launch starts selection; existing diagnostic arguments bypass it; `-dollfightSkipSelection` preserves direct combat development access.

## Execution and acceptance

- [x] Implement full-screen selection with independently editable P1/P2, same-character matches, keyboard/mouse navigation, selected state, real character visuals and map previews.
- [x] Read and preserve original cloud.ply, convert all usable splats with provenance, identify and align the actual platform, add collider and camera, create stage 03.
- [x] Connect opening, back, confirmation, scene load and restart paths. Validate IDs before committing choices. Preserve old diagnostic/replay and settings tools.
- [x] Compile and build the three-scene native app with D3D12. Run focused new/existing selection checks only.
- [x] Use development jumps to capture character selection, each stage preview, cloud early/mid-action/contact and real finishing hit; inspect both fighters' contact with the platform. Check the compact viewport and selection/back/confirm via the native public interfaces. No full-match playback.
- [x] Save useful screenshots and validation notes, document launch and fast-forward controls.

## Verification notes

The targeted Unity tests passed 22/22. All three maps loaded natively; the full 594,371-point Cloud scan and source hashes were verified. Sixteen actual skinned-foot samples raycast onto the measured platform, with the planted-foot early sample within 0.25 mm of the collider. The finishing hit remains r1-combat-20, HP 51/0.

Final output is `outputs/arcade-select/DollFight.exe`, with both existing launchers pointing at it. Evidence is under `outputs/selection-review/native-final/`; implementation and reproduction notes are in `docs/arcade-selection.md`.

The user stopped Computer Use with Escape, so no further desktop input was issued and manual mouse/keyboard acceptance is not claimed. The currently open earlier preview was preserved. A later repository cleanup removed the superseded `outputs/selection-review/native/` screenshots using ordinary deletion after a separate path check. The current build and `native-final` evidence were preserved and their hashes verified.
