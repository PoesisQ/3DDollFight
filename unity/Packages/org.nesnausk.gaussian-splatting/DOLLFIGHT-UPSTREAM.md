# Upstream

- Repository: https://github.com/aras-p/UnityGaussianSplatting
- Commit: `0cc0bf8bb0e9af75ff1c002592024f86057ced58`
- Package: `org.nesnausk.gaussian-splatting` 2.0.0
- License: MIT; original LICENSE.md and file headers are retained.
- Local change: `GatherSplatsForCamera` respects the GameObject layer and camera culling mask. This excludes the scan from DollFight's separate first-person limb cameras.

The scan is separately licensed and is not covered by this package's MIT license.
