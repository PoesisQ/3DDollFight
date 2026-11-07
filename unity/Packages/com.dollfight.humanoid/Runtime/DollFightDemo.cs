using System;
using System.Collections;
using System.IO;
using UnityEngine;
using UnityEngine.Rendering;

namespace DollFight
{
    [Serializable] public class DuelFrame
    {
        public float time, distance, roundRemaining, lastContactTime;
        public int round, roundWinner, matchWinner;
        public bool overtime;
        public float[] health, guardEnergy;
        public int[] wins;
        public string intent, roundState, roundReason, roundLabel, matchState, matchLabel, lastContact;
        public DuelCapsule[] hurtCapsules, attackCapsules;
    }
    [Serializable] public class DuelCapsule
    {
        public int player;
        public string zone;
        public Vector3 a, b;
        public float radius;
    }
    [Serializable] public class DuelTimeline
    {
        public string version, source;
        public string matchMode;
        public string presentationProfile;
        public float presentationRate = .75f;
        public float EffectivePresentationRate => float.IsFinite(presentationRate) && presentationRate > 0 ? presentationRate : .75f;
        public float duration, fps;
        public float regulationDuration = 135, finishTime = -1;
        public int roundCount;
        public DuelFrame[] frames;
        public DuelContact[] contacts;
        public DuelFrame FrameAt(float seconds)
        {
            if (frames == null || frames.Length == 0) return null;
            int low = 0, high = frames.Length - 1, found = 0;
            while (low <= high)
            {
                int middle = low + (high - low) / 2;
                if (frames[middle].time <= seconds) { found = middle; low = middle + 1; }
                else high = middle - 1;
            }
            return frames[found];
        }
    }
    [Serializable] public class PlaybackPerformance
    {
        public string unityVersion, device, note, avatars;
        public string[] characterIds;
        public int width, height, frames, invalidBoneFrames, views;
        public float durationSeconds, averageFps, medianFrameMs, p95FrameMs, maxFrameMs;
    }

    [Serializable] public sealed class NativeReviewResult
    {
        public float replaySeconds, presentedSeconds, requestedSeconds, wallSeconds, resultReadyWallSeconds = -1, totalWallSeconds, presentationRate;
        public string presentationProfile, matchState, finalContact;
        public string[] characterIds;
        public int matchWinner;
        public bool matchFinished, interrupted;
        public float[] health;
    }

    [DefaultExecutionOrder(12000)]
    public sealed class DollFightDemo : MonoBehaviour
    {
        public float PresentationRate => timeline?.EffectivePresentationRate ?? .75f;
        public bool ShowcaseMode => timeline?.presentationProfile == "showcase";
        public bool playing = true, showPlayerViews = false, showSelf = true, showHitboxes;
        [Range(0.1f, 2)] public float speed = 1;
        public float time;
        public string status = "Loading selected characters...";
        public Shader stageShader, lineShader;
        public bool createDefaultEnvironment = true, useMsaa = true;
        public bool Ready { get; private set; }
        public bool EnvironmentReady { get; private set; }
        public DuelSelectionScreen SelectionScreen { get; private set; }
        public bool SelectionOpen => SelectionScreen != null && SelectionScreen.IsOpen;
        public bool CanResumeMatch => !initialMenu;
        public string SelectedStageId => sessionStage ?? StageForScene(UnityEngine.SceneManagement.SceneManager.GetActiveScene().name);
        static string sessionStage;
        static bool enterMatchOnLoad, commandStageApplied;
        bool initialMenu, resumeAfterSelection;
        int selectionCloseFrame = -1;
        public HumanoidReplay[] Actors { get; private set; }
        public Camera MainCamera { get; private set; }
        DuelTimeline timeline;
        DuelCollisionOverlay collisionOverlay;
        NativeClothCage[] cloth;
        Camera[] worldCameras, bodyCameras;
        float fps, lastTime;
        bool seekPending;
        bool naturalMatchEnded;
        bool playbackClockReady, unattendedReview;
        double playbackSample;
        DuelHud hud = new DuelHud();
        public DuelFeedback Feedback { get; private set; }
        public float Duration => timeline?.duration ?? 0;
        public float DisplaySeconds(float sourceSeconds) => sourceSeconds / PresentationRate;
        public bool KnockoutMode => timeline?.matchMode == "knockout";
        public float RegulationDuration => KnockoutMode ? timeline.regulationDuration : Duration;
        public float PlaybackEnd => KnockoutMode && timeline.finishTime >= 0 ? Mathf.Min(Duration, timeline.finishTime) : Duration;
        public bool MatchFinished => CurrentFrame?.matchState == "finished" && (!KnockoutMode ||
            (CurrentFrame.health != null && Array.Exists(CurrentFrame.health, health => health <= 0)));
        public bool PlaybackEnded => naturalMatchEnded || MatchFinished || time >= PlaybackEnd;
        public int RoundCount => Mathf.Max(1, timeline?.roundCount ?? 3);
        public float Fps => fps;
        public Rect ArenaPixels => DuelPresentationLayout.Arena(Screen.width, Screen.height);
        DuelArtDirection artDirection;
        public CharacterCatalog Catalog { get; private set; }
        CharacterSelection selection;
        public CharacterDefinition SelectedCharacter(int player) => Catalog.Get(selection.IdAt(player));
        public string[] CharacterIds => new[] { selection.IdAt(0), selection.IdAt(1) };

        async void Start()
        {
            Application.targetFrameRate = 120;
            QualitySettings.vSyncCount = 0;
            QualitySettings.antiAliasing = useMsaa ? 4 : 0;
            QualitySettings.shadows = ShadowQuality.All;
            QualitySettings.shadowResolution = ShadowResolution.High;
            QualitySettings.shadowDistance = 15;
            Physics.gravity = new Vector3(0, -9.81f, 0);
            Time.fixedDeltaTime = 1f / 60;
            try
            {
                string menuStage = CommandValue("-dollfightMenuStage");
                if (!string.IsNullOrEmpty(menuStage)) StageCatalog.Get(menuStage);
                string requestedStage = CommandValue("-dollfightStage");
                if (!commandStageApplied && !string.IsNullOrEmpty(requestedStage))
                {
                    var stage = StageCatalog.Get(requestedStage);
                    if (!Application.CanStreamedLevelBeLoaded(stage.sceneName))
                        throw new InvalidOperationException("Stage is missing from this build: " + stage.sceneName);
                    commandStageApplied = true; sessionStage = stage.id; enterMatchOnLoad = true;
                    if (UnityEngine.SceneManagement.SceneManager.GetActiveScene().name != stage.sceneName)
                    { UnityEngine.SceneManagement.SceneManager.LoadScene(stage.sceneName); return; }
                }
                initialMenu = !enterMatchOnLoad && !BypassSelection(Environment.GetCommandLineArgs());
                enterMatchOnLoad = false;
                EnvironmentReady = createDefaultEnvironment;
                unattendedReview = Array.Exists(Environment.GetCommandLineArgs(), a => a == "-dollfightUnattendedReview") &&
                    (!string.IsNullOrEmpty(CommandValue("-dollfightRecordReview")) ||
                     !string.IsNullOrEmpty(CommandValue("-dollfightPresentationReview")) ||
                     !string.IsNullOrEmpty(CommandValue("-dollfightCapture")) ||
                     !string.IsNullOrEmpty(CommandValue("-dollfightBenchmark")) ||
                     !string.IsNullOrEmpty(CommandValue("-dollfightGeometryAudit")) ||
                     !string.IsNullOrEmpty(CommandValue("-dollfightSelectionReview")) ||
                     !string.IsNullOrEmpty(CommandValue("-dollfightStagePreview")));
                Catalog = CharacterCatalog.Load();
                selection = CharacterSelection.ForSession(Catalog, Environment.GetCommandLineArgs());
                BuildStage();
                string root = Path.Combine(Application.streamingAssetsPath, "DollFight");
                timeline = JsonUtility.FromJson<DuelTimeline>(File.ReadAllText(Path.Combine(root, "duel.json")));
                if (timeline.version != "dollfight-duel-1" || timeline.frames.Length < 2)
                    throw new InvalidDataException("Unsupported duel timeline");
                collisionOverlay = gameObject.AddComponent<DuelCollisionOverlay>();
                collisionOverlay.Initialize(MainCamera, lineShader);
                Feedback = gameObject.AddComponent<DuelFeedback>();
                Feedback.ignoreApplicationFocus = unattendedReview;
                Feedback.Initialize(MainCamera, lineShader);
                Feedback.ResetAt(0, timeline.contacts);
                Actors = new HumanoidReplay[2]; cloth = new NativeClothCage[2];
                worldCameras = new Camera[2]; bodyCameras = new Camera[2];
                for (int i = 0; i < 2; i++)
                {
                    var character = SelectedCharacter(i);
                    var rootObject = new GameObject($"P{i + 1} {character.id}");
                    var actor = rootObject.AddComponent<HumanoidReplay>();
                    actor.externallyDriven = true; actor.playing = false;
                    if (character.modelKind == "prefab")
                    {
                        var prefab = Resources.Load<GameObject>(character.resourcePath);
                        if (prefab == null) throw new FileNotFoundException($"Missing character prefab: {character.id} ({character.resourcePath})");
                        var model = Instantiate(prefab, rootObject.transform);
                        actor.existingHumanoid = model.GetComponent<Animator>();
                        if (actor.existingHumanoid == null || actor.existingHumanoid.avatar == null || !actor.existingHumanoid.avatar.isHuman)
                            throw new InvalidDataException($"Character prefab requires a Humanoid Animator: {character.id}");
                    }
                    await actor.LoadAsync(character.modelKind == "vrm" ? Path.Combine(root, character.modelFile) : null,
                        File.ReadAllText(Path.Combine(root, $"player-{i + 1}-motion.json")));
                    Actors[i] = actor;
                    // Cloth bind pose must be constructed in the imported rest
                    // pose; the loader initializes at t=0, so restore initial
                    // Transform states while building the physics proxy.
                    actor.RestoreBindPose();
                    if (actor.Instance != null) ApplyLitSurfaces(actor);
                    if (!string.IsNullOrEmpty(character.clothFile))
                    {
                        cloth[i] = rootObject.AddComponent<NativeClothCage>();
                        cloth[i].Initialize(actor, JsonUtility.FromJson<ClothCageData>(
                            File.ReadAllText(Path.Combine(root, character.clothFile))));
                    }
                    actor.Apply(0);
                    worldCameras[i] = MakeCamera($"Player {i + 1} opponent", 70, 2 + i * 2);
                    bodyCameras[i] = MakeCamera($"Player {i + 1} body", 78, 3 + i * 2);
                    bodyCameras[i].clearFlags = CameraClearFlags.Depth;
                    bodyCameras[i].nearClipPlane = 0.025f;
                    worldCameras[i].cullingMask = MainMask & ~(1 << (8 + i * 2)) & ~(1 << (12 + i));
                    bodyCameras[i].cullingMask = (1 << (9 + i * 2)) | (1 << (12 + i));
                    rootObject.AddComponent<FirstPersonBody>().Initialize(actor, bodyCameras[i], 8 + i * 2, 9 + i * 2, character.firstPersonShoulderOffset);
                }
                Ready = true; artDirection.CapturePortraits(); hud.Reset(CurrentFrame); status = $"Unity / Humanoid / P1 {SelectedCharacter(0).displayName} ({selection.IdAt(0)}) / P2 {SelectedCharacter(1).displayName} ({selection.IdAt(1)})";
                SelectionScreen = gameObject.AddComponent<DuelSelectionScreen>();
                SelectionScreen.Initialize(this);
                if (initialMenu && !string.IsNullOrEmpty(menuStage)) SelectionScreen.SelectStage(StageCatalog.Get(menuStage).id);
                if (initialMenu) OpenCharacterSelection();
                else SelectionScreen.Hide();
                StartCoroutine(EstablishPlaybackClock());
                Debug.Log("DOLLFIGHT_READY " + status);
                string preview = CommandValue("-dollfightStagePreview");
                if (!string.IsNullOrEmpty(preview)) { StartCoroutine(CaptureStagePreview(preview)); return; }
                string selectionReview = CommandValue("-dollfightSelectionReview");
                if (!string.IsNullOrEmpty(selectionReview) && FindFirstObjectByType<NativeSelectionReview>() == null)
                    new GameObject("Fast selection review").AddComponent<NativeSelectionReview>().Begin(selectionReview);
                string presentation = CommandValue("-dollfightPresentationReview");
                if (!string.IsNullOrEmpty(presentation)) { StartCoroutine(PresentationReview(presentation)); return; }
                string capture = CommandValue("-dollfightCapture");
                if (!string.IsNullOrEmpty(capture)) StartCoroutine(CaptureReview(capture));
                else
                {
                    string benchmark = CommandValue("-dollfightBenchmark");
                    if (!string.IsNullOrEmpty(benchmark)) StartCoroutine(Benchmark(benchmark));
                    string record = CommandValue("-dollfightRecordReview");
                    if (!string.IsNullOrEmpty(record)) StartCoroutine(RecordReview(record));
                }
            }
            catch (Exception e) { status = e.Message; Debug.LogException(e); }
        }

        const int MainMask = ~(1 << 9 | 1 << 11 | 1 << 31);

        IEnumerator EstablishPlaybackClock()
        {
            // Loading and first-render work must finish before the playback clock starts.
            yield return new WaitForEndOfFrame();
            yield return null;
            playbackSample = Time.realtimeSinceStartupAsDouble;
            playbackClockReady = true;
        }

        void ApplyLitSurfaces(HumanoidReplay actor)
        {
            var done = new System.Collections.Generic.HashSet<Material>();
            foreach (var renderer in actor.ModelRoot.GetComponentsInChildren<Renderer>())
                foreach (var material in renderer.sharedMaterials)
                {
                    if (!done.Add(material) || material.shader.name != "UniGLTF/UniUnlit") continue;
                    string name = material.name;
                    if (!(name.Contains("SKIN") || name.Contains("cel skin") || name.StartsWith("tripo_material") || name.StartsWith("AuthoredHair"))) continue;
                    Texture texture = material.mainTexture; Color tint = material.color;
                    material.shader = stageShader;
                    material.mainTexture = texture; material.color = tint;
                    material.SetFloat("_Glossiness", name.Contains("Hair") ? 0.28f : 0.18f);
                    material.SetFloat("_Metallic", 0);
                    renderer.receiveShadows = true;
                }
        }

        void LateUpdate()
        {
            if (!Ready) { hud.Tick(null); return; }
            double now = Time.realtimeSinceStartupAsDouble;
            float playbackDelta = playbackClockReady ? (float)Math.Max(0, now - playbackSample) : 0;
            playbackSample = now;
            Feedback.RestoreCamera(MainCamera);
            if (Input.GetKeyDown(KeyCode.T) && !SelectionOpen) OpenCharacterSelection();
            if (SelectionOpen || !EnvironmentReady || selectionCloseFrame == Time.frameCount)
            {
                Feedback.Advance(time, time, timeline.contacts, false);
                collisionOverlay.Show(CurrentFrame, false);
                return;
            }
            if (Input.GetKeyDown(KeyCode.Escape)) hud.SettingsOpen = !hud.SettingsOpen;
            if (Input.GetKeyDown(KeyCode.M)) Feedback.soundEnabled = !Feedback.soundEnabled;
            if (Input.GetKeyDown(KeyCode.N)) Feedback.shakeEnabled = !Feedback.shakeEnabled;
            if (Input.GetKeyDown(KeyCode.Space)) TogglePlayback();
            if (Input.GetKeyDown(KeyCode.R)) Restart();
            if (Input.GetKeyDown(KeyCode.V)) TogglePlayerViews();
            if (Input.GetKeyDown(KeyCode.H)) showSelf = !showSelf;
            if (Input.GetKeyDown(KeyCode.B)) showHitboxes = !showHitboxes;
            float previousTime = time;
            if (playing)
            {
                time = Mathf.Min(time + Feedback.PlaybackDelta(playbackDelta * speed * PresentationRate), PlaybackEnd);
            }
            Feedback.Advance(previousTime, time, timeline.contacts, playing || naturalMatchEnded);
            if (playing && (time >= PlaybackEnd || MatchFinished)) { playing = false; naturalMatchEnded = true; }
            bool jumped = seekPending || time < lastTime || Mathf.Abs(time - lastTime) > 0.2f;
            seekPending = false;
            if (jumped) hud.Reset(CurrentFrame);
            for (int i = 0; i < 2; i++)
            {
                Actors[i].Apply(time);
                cloth[i]?.UpdateGuide();
                if (jumped) { Actors[i].ResetSecondary(); cloth[i]?.ResetSimulation(); }
                Actors[i].ProcessSecondary();
                cloth[i]?.Draw();
            }
            lastTime = time;
            fps = Mathf.Lerp(fps, 1 / Mathf.Max(Time.unscaledDeltaTime, 0.001f), 0.05f);
            UpdateCameras();
            Feedback.ApplyCamera(MainCamera);
            hud.Tick(CurrentFrame);
            collisionOverlay.Show(CurrentFrame, showHitboxes);
        }

        public DuelFrame CurrentFrame => Ready ? timeline.FrameAt(time) : null;

        public void Seek(float seconds)
        {
            if (timeline == null) return;
            time = Mathf.Clamp(seconds, 0, timeline.duration);
            naturalMatchEnded = false;
            lastTime = time; seekPending = true;
            Feedback?.ResetAt(time, timeline.contacts);
            hud.Reset(CurrentFrame);
        }

        public void Restart() { Seek(0); playing = true; }
        public void TogglePlayerViews() { showPlayerViews = !showPlayerViews; }
        public void CycleSpeed() { speed = speed == 1 ? .75f : speed == .75f ? .5f : speed == .5f ? .25f : speed == .25f ? 1.25f : 1; }
        public void SkipToNextContact(bool hitsOnly = false)
        {
            if (!Ready) return;
            foreach (var contact in timeline.contacts ?? Array.Empty<DuelContact>())
                if (contact.time > time + .03f && (!hitsOnly || contact.damage > 0))
                { Seek(Mathf.Max(0, contact.time - .25f)); playing = true; return; }
        }
        public void SkipToFinish() { if (Ready) { Seek(Mathf.Max(0, PlaybackEnd - .3f)); playing = true; } }
        public void TogglePlayback()
        {
            if (!Ready) return;
            if (PlaybackEnded) { Seek(0); playing = true; }
            else playing = !playing;
            if (!playing) { naturalMatchEnded = false; Feedback?.ResetAt(time, timeline.contacts); }
        }

        /// <summary>Atomically select both zero-based player slots and restart the scene. Mirrors are allowed.</summary>
        public void SelectCharacters(string playerOneId, string playerTwoId)
        {
            if (selection == null) throw new InvalidOperationException("Character selection is not initialized");
            selection.Apply(playerOneId, playerTwoId);
            enterMatchOnLoad = true;
            Feedback?.ResetAt(time, timeline?.contacts);
            UnityEngine.SceneManagement.SceneManager.LoadScene(UnityEngine.SceneManagement.SceneManager.GetActiveScene().name);
        }

        /// <summary>Validate every choice before changing the session or loading another stage.</summary>
        public void StartMatch(string playerOneId, string playerTwoId, string stageId)
        {
            if (selection == null || Catalog == null) throw new InvalidOperationException("Character selection is not initialized");
            Catalog.Get(playerOneId); Catalog.Get(playerTwoId);
            var stage = StageCatalog.Get(stageId);
            if (!Application.CanStreamedLevelBeLoaded(stage.sceneName))
                throw new InvalidOperationException("Stage is missing from this build: " + stage.sceneName);
            selection.Apply(playerOneId, playerTwoId);
            sessionStage = stage.id; enterMatchOnLoad = true;
            Feedback?.ResetAt(time, timeline?.contacts);
            UnityEngine.SceneManagement.SceneManager.LoadScene(stage.sceneName);
        }

        public void OpenCharacterSelection()
        {
            if (SelectionScreen == null) return;
            if (!SelectionOpen) resumeAfterSelection = playing;
            playing = false; hud.SettingsOpen = false;
            Feedback?.ResetAt(time, timeline?.contacts);
            SelectionScreen.ShowCharacters();
        }

        public void OpenStageSelection()
        {
            if (!SelectionOpen) OpenCharacterSelection();
            SelectionScreen?.ShowStages();
        }

        public void ResumeFromSelection()
        {
            SelectionScreen?.Hide();
            initialMenu = false;
            playing = resumeAfterSelection && EnvironmentReady;
            selectionCloseFrame = Time.frameCount;
            playbackSample = Time.realtimeSinceStartupAsDouble;
        }

        public void MarkEnvironmentReady()
        {
            EnvironmentReady = true;
            bool diagnostic = false;
            foreach (string option in new[] { "-dollfightRecordReview", "-dollfightPresentationReview", "-dollfightCapture",
                "-dollfightBenchmark", "-dollfightGeometryAudit", "-dollfightSelectionReview", "-dollfightStagePreview", "-runTests" })
                if (Array.IndexOf(Environment.GetCommandLineArgs(), option) >= 0) diagnostic = true;
            if (!SelectionOpen && !initialMenu && !diagnostic) playing = true;
            playbackSample = Time.realtimeSinceStartupAsDouble;
        }

        public static bool BypassSelection(string[] args)
        {
            foreach (string value in args ?? Array.Empty<string>())
                if (value == "-runTests" || value == "-dollfightSkipSelection" || value == "-dollfightStage" || value == "-churchReview" ||
                    value == "-dollfightRecordReview" || value == "-dollfightPresentationReview" || value == "-dollfightCapture" ||
                    value == "-dollfightBenchmark" || value == "-dollfightGeometryAudit" || value == "-dollfightStagePreview") return true;
            return false;
        }

        static string StageForScene(string scene)
        {
            foreach (var stage in StageCatalog.All) if (stage.sceneName == scene) return stage.id;
            return "underground";
        }

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.SubsystemRegistration)]
        static void ResetSelectionFlow() { sessionStage = null; enterMatchOnLoad = commandStageApplied = false; }

        void UpdateCameras()
        {
            Rect arena = ArenaPixels;
            DuelPresentationLayout.Apply(MainCamera, arena, Screen.width, Screen.height);
            for (int i = 0; i < 2; i++)
            {
                var head = Actors[i].Bones[4].position;
                var ownHip = Actors[i].Bones[0].position;
                var opponent = Actors[1 - i].Bones[0].position;
                Vector3 forward = opponent - ownHip; forward.y = 0; forward.Normalize();
                Rect rect = DuelPresentationLayout.PlayerView(arena, hud.DisplaySide(this, i));
                var world = worldCameras[i]; var body = bodyCameras[i];
                world.enabled = showPlayerViews; body.enabled = showPlayerViews && showSelf;
                DuelPresentationLayout.Apply(world, rect, Screen.width, Screen.height);
                DuelPresentationLayout.Apply(body, rect, Screen.width, Screen.height);
                // A stable combat view keeps the opponent readable at close
                // range. Own-body overlay uses an anatomically anchored eye.
                world.transform.position = new Vector3(ownHip.x, 1.35f, ownHip.z) - forward * 0.65f;
                world.transform.LookAt(new Vector3(opponent.x, 0.88f, opponent.z));
                // Virtual eye is stabilized above the torso; the small rear
                // offset gives the view mesh safe depth even during a high guard.
                // It never modifies the shared skeleton or hit geometry.
                body.transform.position = new Vector3(ownHip.x, Mathf.Max(head.y + 0.10f, ownHip.y + 0.58f), ownHip.z) + forward * 0.10f;
                body.transform.rotation = Quaternion.LookRotation(forward, Vector3.up) * Quaternion.Euler(6, 0, 0);
            }
        }

        Camera MakeCamera(string label, float fov, float depth)
        {
            var camera = new GameObject(label).AddComponent<Camera>();
            camera.fieldOfView = fov; camera.depth = depth;
            camera.nearClipPlane = 0.05f; camera.farClipPlane = 30;
            camera.clearFlags = CameraClearFlags.SolidColor;
            camera.backgroundColor = new Color(0.035f, 0.05f, 0.075f);
            camera.cullingMask = MainMask;
            camera.allowHDR = true;
            return camera;
        }

        void BuildStage()
        {
            artDirection = gameObject.AddComponent<DuelArtDirection>();
            artDirection.Initialize(this, stageShader, lineShader);
            MainCamera = MakeCamera("Main arena camera", createDefaultEnvironment ? 46 : 50, 0);
            MainCamera.transform.position = createDefaultEnvironment ? new Vector3(.8f, 1.6f, 3.5f) : new Vector3(1.65f, 1.8f, 4.05f);
            MainCamera.transform.LookAt(new Vector3(0, createDefaultEnvironment ? 1.3f : 1.2f, 0));
            MainCamera.gameObject.AddComponent<AudioListener>();
        }

        void OnGUI()
        {
            if (SelectionOpen) return;
            Matrix4x4 matrix = GUI.matrix;
            Color color = GUI.color, background = GUI.backgroundColor, content = GUI.contentColor;
            bool enabled = GUI.enabled;
            try
            {
                GUI.matrix = Matrix4x4.identity;
                GUI.color = GUI.backgroundColor = GUI.contentColor = Color.white;
                Feedback?.DrawOverlay(ArenaPixels);
                hud.Draw(this, ArenaPixels);
            }
            finally
            {
                GUI.matrix = matrix; GUI.color = color; GUI.backgroundColor = background;
                GUI.contentColor = content; GUI.enabled = enabled;
            }
        }

        IEnumerator CaptureStagePreview(string path)
        {
            while (!EnvironmentReady) yield return null;
            playing = false; Seek(0); showPlayerViews = false;
            foreach (var actor in Actors) actor.gameObject.SetActive(false);
            var contactShadows = new System.Collections.Generic.List<Renderer>();
            foreach (var renderer in artDirection.GetComponentsInChildren<Renderer>(true))
                if (renderer.name == "Soft sole ground contact" && renderer.enabled)
                { contactShadows.Add(renderer); renderer.enabled = false; }
            for (int i = 0; i < 8; i++) yield return null;
            yield return new WaitForEndOfFrame();
            Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(path)));
            var target = RenderTexture.GetTemporary(1440, 810, 24, RenderTextureFormat.ARGB32);
            var previousTarget = MainCamera.targetTexture;
            var previousRect = MainCamera.rect;
            var previousActive = RenderTexture.active;
            var image = new Texture2D(1440, 810, TextureFormat.RGB24, false);
            try
            {
                MainCamera.rect = new Rect(0, 0, 1, 1); MainCamera.targetTexture = target;
                MainCamera.Render(); RenderTexture.active = target;
                image.ReadPixels(new Rect(0, 0, 1440, 810), 0, 0); image.Apply();
                File.WriteAllBytes(path, image.EncodeToPNG());
            }
            finally
            {
                MainCamera.targetTexture = previousTarget; MainCamera.rect = previousRect;
                RenderTexture.active = previousActive; RenderTexture.ReleaseTemporary(target); Destroy(image);
                foreach (var actor in Actors) actor.gameObject.SetActive(true);
                foreach (var renderer in contactShadows) renderer.enabled = true;
            }
            File.WriteAllText(path + ".txt", $"scene={UnityEngine.SceneManagement.SceneManager.GetActiveScene().name}\nstage={SelectedStageId}\nenvironmentReady={EnvironmentReady}\nsource=native camera render; no combat HUD or fighters\n");
            Debug.Log("DOLLFIGHT_STAGE_PREVIEW_COMPLETE " + path);
            if (Array.Exists(Environment.GetCommandLineArgs(), a => a == "-dollfightReviewQuit")) Application.Quit();
        }

        void OnApplicationFocus(bool focused)
        {
            if (!focused && Ready && !unattendedReview) { playing = false; naturalMatchEnded = false; Feedback?.ResetAt(time, timeline.contacts); }
        }

        IEnumerator PresentationReview(string folder)
        {
            Directory.CreateDirectory(folder);
            yield return new WaitForSecondsRealtime(3);
            playing = false; speed = 1; showPlayerViews = false;
            var summary = new System.Text.StringBuilder();
            summary.AppendLine($"characterIds={string.Join(",", CharacterIds)}");
            summary.AppendLine($"presentationRate={PresentationRate:0.00} displayedDuration={DisplaySeconds(Duration):0.000} regulationSeconds={DisplaySeconds(RegulationDuration):0.000} mode={timeline.matchMode} finishTime={timeline.finishTime:0.000}");
            Seek(0); playing = true;
            yield return new WaitForEndOfFrame();
            ScreenCapture.CaptureScreenshot(Path.Combine(folder, "intro-ready.png"));
            float introDeadline = Time.realtimeSinceStartup + 4;
            while (time < .82f && playing && Time.realtimeSinceStartup < introDeadline) yield return null;
            yield return new WaitForEndOfFrame();
            ScreenCapture.CaptureScreenshot(Path.Combine(folder, "intro-fight.png"));
            float clockStart = Time.realtimeSinceStartup, sourceStart = time;
            while (Time.realtimeSinceStartup - clockStart < 2) yield return new WaitForEndOfFrame();
            float wallDelta = Time.realtimeSinceStartup - clockStart, sourceDelta = time - sourceStart;
            summary.AppendLine($"continuousClock wallDelta={wallDelta:0.000000} sourceDelta={sourceDelta:0.000000} displayedDelta={DisplaySeconds(sourceDelta):0.000000} measuredSourceRate={sourceDelta / wallDelta:0.000000}");
            playing = false;
            foreach (var size in new[] { new Vector2Int(1440, 900), new Vector2Int(960, 640), new Vector2Int(1920, 900) })
            {
                Screen.SetResolution(size.x, size.y, false); Seek(13.7f);
                for (int i = 0; i < 24; i++) yield return null;
                yield return new WaitForEndOfFrame();
                ScreenCapture.CaptureScreenshot(Path.Combine(folder, $"arena-{size.x}x{size.y}.png"));
                summary.AppendLine($"screen={Screen.width}x{Screen.height} arena={ArenaPixels} aspect={MainCamera.aspect:0.000000} displayedElapsed={DisplaySeconds(time):0.000} displayedDuration={DisplaySeconds(Duration):0.000}");
                yield return null;
            }
            Screen.SetResolution(1440, 900, false); showPlayerViews = true;
            for (int i = 0; i < 24; i++) yield return null;
            yield return new WaitForEndOfFrame();
            ScreenCapture.CaptureScreenshot(Path.Combine(folder, "player-views.png")); yield return null;
            showPlayerViews = false; hud.SettingsOpen = true;
            for (int i = 0; i < 24; i++) yield return null;
            yield return new WaitForEndOfFrame();
            ScreenCapture.CaptureScreenshot(Path.Combine(folder, "settings.png")); yield return null;
            hud.DebugOpen = true;
            for (int i = 0; i < 12; i++) yield return null;
            yield return new WaitForEndOfFrame();
            ScreenCapture.CaptureScreenshot(Path.Combine(folder, "debug-tools.png")); yield return null;
            hud.DebugOpen = false;
            hud.SettingsOpen = false;
            for (int i = 0; i < 20; i++) yield return null;
            int index = 0;
            foreach (var contact in timeline.contacts ?? Array.Empty<DuelContact>())
            {
                if (contact.damage <= 0 || index >= 3) continue;
                Seek(Mathf.Max(0, contact.time - .12f)); playing = true;
                float deadline = Time.realtimeSinceStartup + 3;
                while (time < contact.time && Time.realtimeSinceStartup < deadline) yield return null;
                yield return new WaitForEndOfFrame();
                ScreenCapture.CaptureScreenshot(Path.Combine(folder, $"contact-{index++}.png"));
                summary.AppendLine($"contact expected={contact.id} observed={Feedback.LastContact?.id} age={Feedback.ContactAge:0.000} playback={time:0.000}");
                yield return null; playing = false;
            }
            float kickSample = ReviewKickTime();
            Seek(kickSample); playing = false;
            for (int i = 0; i < 24; i++) yield return null;
            yield return new WaitForEndOfFrame();
            ScreenCapture.CaptureScreenshot(Path.Combine(folder, "airborne-kick-" + kickSample.ToString("00.0", System.Globalization.CultureInfo.InvariantCulture) + ".png"));
            summary.AppendLine($"aerialSample={kickSample:0.000} intent={CurrentFrame?.intent}"); yield return null;
            SkipToFinish();
            float finishDeadline = Time.realtimeSinceStartup + 4;
            while (playing && Time.realtimeSinceStartup < finishDeadline) yield return null;
            yield return new WaitForEndOfFrame();
            ScreenCapture.CaptureScreenshot(Path.Combine(folder, KnockoutMode ? "ko-result.png" : "match-result.png"));
            summary.AppendLine($"result mode={timeline.matchMode} finishTime={timeline.finishTime:0.000} playback={time:0.000} matchState={CurrentFrame.matchState} matchWinner={CurrentFrame.matchWinner} health={string.Join(",", CurrentFrame.health ?? Array.Empty<float>())} finalContact={Feedback.LastContact?.id}");
            yield return null;
            yield return new WaitForSecondsRealtime(1.35f);
            yield return new WaitForEndOfFrame();
            ScreenCapture.CaptureScreenshot(Path.Combine(folder, "result-settled.png"));
            yield return null;
            File.WriteAllText(Path.Combine(folder, "presentation-summary.txt"), summary.ToString());
            File.WriteAllText(Path.Combine(folder, "presentation-complete.txt"), status);
            Debug.Log("DOLLFIGHT_PRESENTATION_COMPLETE " + folder);
            if (Array.Exists(Environment.GetCommandLineArgs(), a => a == "-dollfightReviewQuit")) Application.Quit();
        }
        static string CommandValue(string name)
        {
            string[] args = Environment.GetCommandLineArgs();
            int index = Array.IndexOf(args, name);
            return index >= 0 && index + 1 < args.Length ? args[index + 1] : null;
        }

        public float ReviewKickTime()
        {
            if (float.TryParse(CommandValue("-dollfightReviewKickTime"), System.Globalization.NumberStyles.Float,
                System.Globalization.CultureInfo.InvariantCulture, out float requested) && float.IsFinite(requested))
                return Mathf.Clamp(requested, 0, PlaybackEnd);
            if (ShowcaseMode)
                foreach (string word in new[] { "腾空", "旋踢" })
                    for (int i = 0; i < timeline.frames.Length; i++)
                    {
                        if (!(timeline.frames[i].intent?.Contains(word) ?? false)) continue;
                        int end = i;
                        while (end + 1 < timeline.frames.Length && (timeline.frames[end + 1].intent?.Contains(word) ?? false)) end++;
                        return Mathf.Clamp((timeline.frames[i].time + timeline.frames[end].time) * .5f, 0, PlaybackEnd);
                    }
            return Mathf.Min(84.2f, PlaybackEnd);
        }

        IEnumerator CaptureReview(string folder)
        {
            Directory.CreateDirectory(folder);
            playing = false;
            foreach (float sample in new[] { 1.5f, 4.1f, 8.3f, 8.8f, 13.7f, 43.5f, 83.7f, 84.2f, 86.5f })
            {
                Seek(sample);
                for (int i = 0; i < 30; i++) yield return null;
                yield return new WaitForEndOfFrame();
                ScreenCapture.CaptureScreenshot(Path.Combine(folder, $"unity-{sample:00.0}.png"));
                yield return null;
            }
            File.WriteAllText(Path.Combine(folder, "capture-complete.txt"), status);
            playing = true;
        }

        IEnumerator Benchmark(string path)
        {
            yield return new WaitForSecondsRealtime(3);
            float requestedDuration = 90;
            if (float.TryParse(CommandValue("-dollfightBenchmarkSeconds"),
                System.Globalization.NumberStyles.Float, System.Globalization.CultureInfo.InvariantCulture, out float seconds)
                && float.IsFinite(seconds)) requestedDuration = Mathf.Clamp(seconds, 1, 1800);
            int views = int.TryParse(CommandValue("-dollfightBenchmarkViews"), out int requestedViews) && requestedViews == 1 ? 1 : 3;
            Seek(0); playing = true; speed = 1; showPlayerViews = views == 3; showSelf = true;
            var samples = new System.Collections.Generic.List<float>(12000);
            int invalid = 0;
            float elapsed = 0;
            while (elapsed < requestedDuration)
            {
                yield return null;
                float delta = Time.unscaledDeltaTime;
                samples.Add(delta * 1000); elapsed += delta;
                bool bad = false;
                foreach (var actor in Actors)
                    foreach (var bone in actor.Bones)
                        if (!float.IsFinite(bone.position.sqrMagnitude)) bad = true;
                if (bad) invalid++;
            }
            samples.Sort();
            var result = new PlaybackPerformance
            {
                unityVersion = Application.unityVersion, device = SystemInfo.graphicsDeviceName,
                avatars = SelectedCharacter(0).displayName + " + " + SelectedCharacter(1).displayName,
                characterIds = CharacterIds,
                width = Screen.width, height = Screen.height, frames = samples.Count, views = views,
                invalidBoneFrames = invalid, durationSeconds = elapsed,
                averageFps = samples.Count / elapsed,
                medianFrameMs = samples[samples.Count / 2],
                p95FrameMs = samples[Mathf.Min(samples.Count - 1, Mathf.FloorToInt(samples.Count * 0.95f))],
                maxFrameMs = samples[samples.Count - 1],
                note = FormattableString.Invariant($"{elapsed:0.000} seconds, {views} views") +
                    (views == 3 ? " plus 2 own-limb overlays and view-only IK" : " (main arena camera)") +
                    "; original meshes; guided native cloth and VRM springs; target 120 fps; not camera-input latency."
            };
            Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(path)));
            File.WriteAllText(path, JsonUtility.ToJson(result, true));
            Debug.Log("DOLLFIGHT_BENCHMARK_COMPLETE " + path);
            if (Array.Exists(Environment.GetCommandLineArgs(), a => a == "-dollfightReviewQuit")) Application.Quit();
        }

        IEnumerator RecordReview(string folder)
        {
            Directory.CreateDirectory(folder);
            foreach (string metadata in new[] { "complete.json", "cancelled.json", "cancelled.txt" })
                File.Delete(Path.Combine(folder, metadata));
            playing = false; Seek(0);
            string ffmpeg = CommandValue("-dollfightFfmpeg");
            NativeReviewRecorder recorder = null;
            float duration = PlaybackEnd;
            if (float.TryParse(CommandValue("-dollfightRecordSeconds"),
                System.Globalization.NumberStyles.Float, System.Globalization.CultureInfo.InvariantCulture, out float limit))
                duration = Mathf.Clamp(limit, 1, duration);
            if (!string.IsNullOrEmpty(ffmpeg))
                recorder = new NativeReviewRecorder(ffmpeg, Path.Combine(folder, "review.mp4"), Screen.width, Screen.height);
            File.WriteAllText(Path.Combine(folder, "ready.txt"), status);
            if (recorder == null)
                while (!File.Exists(Path.Combine(folder, "start.txt"))) yield return null;
            // Warm both rendering and capture setup before resetting the recording origin.
            while (!playbackClockReady) yield return null;
            var endOfFrame = new WaitForEndOfFrame();
            for (int i = 0; i < 3; i++) yield return endOfFrame;
            Seek(0);
            yield return endOfFrame;
            recorder?.Capture(0);
            playing = true; speed = 1;
            playbackSample = Time.realtimeSinceStartupAsDouble;
            float begin = Time.realtimeSinceStartup;
            int frames = 1;
            while (time < duration && !MatchFinished && playing)
            {
                yield return endOfFrame;
                int frame = Mathf.FloorToInt((Time.realtimeSinceStartup - begin) * 30);
                frames = Mathf.Max(frames, frame + 1);
                recorder?.Capture(frame);
                if (recorder?.Error != null) break;
            }
            bool interrupted = !MatchFinished && (time < duration || (KnockoutMode && duration == PlaybackEnd));
            playing = false;
            float elapsed = Time.realtimeSinceStartup - begin;
            float resultReadyElapsed = -1;
            if (MatchFinished && !interrupted)
            {
                float resultDeadline = Time.realtimeSinceStartup + 1.35f;
                while (Time.realtimeSinceStartup < resultDeadline)
                {
                    yield return endOfFrame;
                    int frame = Mathf.FloorToInt((Time.realtimeSinceStartup - begin) * 30);
                    frames = Mathf.Max(frames, frame + 1); recorder?.Capture(frame);
                }
                resultReadyElapsed = Time.realtimeSinceStartup - begin;
                ScreenCapture.CaptureScreenshot(Path.Combine(folder, "result-settled.png"));
                yield return null;
            }
            if (interrupted)
                File.WriteAllText(Path.Combine(folder, "cancelled.txt"), "Playback interrupted before requested duration (pause, focus loss, or recorder error).");
            if (recorder != null)
            {
                while (recorder.Pending) yield return null;
                recorder.Finish(frames);
                while (!recorder.Complete) yield return null;
                string error = recorder.Error;
                File.WriteAllText(Path.Combine(folder, "capture.json"),
                    "{\"capturedFrames\":" + recorder.CapturedFrames + ",\"repeatedFrames\":" + recorder.RepeatedFrames + "}");
                recorder.Dispose();
                if (error != null)
                {
                    File.WriteAllText(Path.Combine(folder, "error.txt"), error);
                    if (Array.Exists(Environment.GetCommandLineArgs(), a => a == "-dollfightReviewQuit")) Application.Quit();
                    yield break;
                }
            }
            var result = new NativeReviewResult
            {
                characterIds = CharacterIds,
                replaySeconds = time, presentedSeconds = DisplaySeconds(time), requestedSeconds = duration,
                wallSeconds = elapsed, resultReadyWallSeconds = resultReadyElapsed, totalWallSeconds = Time.realtimeSinceStartup - begin,
                presentationRate = PresentationRate, presentationProfile = timeline.presentationProfile,
                matchState = CurrentFrame?.matchState, matchWinner = CurrentFrame?.matchWinner ?? -1,
                matchFinished = MatchFinished, interrupted = interrupted, health = CurrentFrame?.health, finalContact = Feedback.LastContact?.id
            };
            File.WriteAllText(Path.Combine(folder, interrupted ? "cancelled.json" : "complete.json"), JsonUtility.ToJson(result, true));
            Debug.Log("DOLLFIGHT_RECORD_COMPLETE " + folder);
            if (Array.Exists(Environment.GetCommandLineArgs(), a => a == "-dollfightReviewQuit")) Application.Quit();
        }

        void OnDestroy()
        {
            hud.Dispose();
        }
    }
}
