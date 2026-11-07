# DollFight Arcade Art Direction Implementation Plan

> Use executing-plans for independent implementation work and verification-before-completion for the final checks. Work in the current checkout because required ongoing Unity/KO work and local scene assets are uncommitted here. Preserve those changes; do not commit unrelated work.

**Goal:** Ship a visibly stronger native game presentation and both rebuilt launchers.

**Architecture:** Keep the existing event and match pipeline. Isolate HUD drawing, stage/look/portraits, and contact effects in separate components. Unity Built-in Render Pipeline and IMGUI remain the runtime; no new package dependency.

**Tech Stack:** Unity 6000.3.27f1, C#, Built-in shaders, local CC0/OFL assets.

## Work packages

- [ ] HUD: `DuelHud.cs` plus optional `DuelUiArt.cs`, local fonts under `Assets/Resources/DollFight/Fonts`. Rebuild bar/name/timer composition, segmented guard, impact callouts, cinematic intro/KO, actionable results and settings. Use existing methods for all controls. Optional portraits via `demo.GetComponent<DuelArtDirection>()?.Portrait(player)` returning `Texture`. Preserve `Draw`, `Tick`, `Reset`, `Dispose`, `SettingsOpen`, `DebugOpen` contracts.
- [ ] Art direction: new `DuelArtDirection.cs` (owns runtime resources), optional stage/look shader assets, local textures under `Assets/Resources/DollFight/Textures`. Own integration in `DollFightDemo.cs`. Build an industrial stage, tune lighting, provide one-time local portrait captures, add subtle grading only if compatible with Gaussian Splat rendering. Preserve camera framing and clocks. `public Texture Portrait(int player)` is the HUD contract. Extend review capture for intro, final settled result and ultrawide.
- [ ] Impact: `DuelFeedback.cs` and optional local audio under `Assets/Resources/DollFight/Audio`. Improve directional impact shapes, sparks and layered sound. Preserve real-event consumption, no duplicate feedback, reset semantics, hitstop timing and tests. Keep actor faces readable.
- [ ] Integration: inspect combined diff, run Unity EditMode, build ordinary and church players sequentially, run the presentation review for both, inspect images/logs, exercise actual controls. Fix observed issues with focused checks.
- [ ] Delivery: record assets in separate attribution files, update `docs/combat-presentation.md` and launch documentation, save representative screenshots and performance evidence under ignored `outputs/arcade-polish/`.

## Commands and acceptance

`unity test unity --mode EditMode --output outputs/arcade-polish/editmode.xml` must pass.

`unity run unity --no-tail --log-file outputs/arcade-polish/build-studio.log -- -executeMethod DollFight.Editor.DemoBuild.BuildWindows` must report `DOLLFIGHT_BUILD_OK`. The CLI manages `-quit` itself.

`unity run unity --no-tail --log-file outputs/arcade-polish/build-church.log -- -executeMethod DollFight.Environments.Editor.SaintMauriceScene.BuildDuel` must succeed.

Run each executable with `-dollfightPresentationReview <absolute-output-dir> -dollfightReviewQuit -screen-fullscreen 0 -screen-width 1440 -screen-height 900`, church additionally with `-force-d3d12`. Both must produce completion markers, accurate KO health, readable settings and undistorted arenas. Asset attribution must describe only files actually included.
