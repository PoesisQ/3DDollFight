using System;
using System.Collections;
using System.IO;
using UnityEngine;
using UnityEngine.Rendering;

namespace DollFight
{
    [Serializable] public class DuelFrame
    {
        public float time, distance;
        public int round;
        public float[] health;
        public string intent;
    }
    [Serializable] public class DuelTimeline
    {
        public string version, source;
        public float duration, fps;
        public DuelFrame[] frames;
    }
    [Serializable] public class PlaybackPerformance
    {
        public string unityVersion, device, note, avatars;
        public int width, height, frames, invalidBoneFrames;
        public float durationSeconds, averageFps, medianFrameMs, p95FrameMs, maxFrameMs;
    }

    [DefaultExecutionOrder(12000)]
    public sealed class DollFightDemo : MonoBehaviour
    {
        public bool playing = true, showPlayerViews = true, showSelf = true;
        [Range(0.1f, 2)] public float speed = 1;
        public float time;
        public string status = "Loading VRM avatars...";
        public Shader stageShader, lineShader;
        public bool Ready { get; private set; }
        public HumanoidReplay[] Actors { get; private set; }
        public Camera MainCamera { get; private set; }
        DuelTimeline timeline;
        NativeClothCage[] cloth;
        Camera[] worldCameras, bodyCameras;
        float fps, lastTime;
        GUIStyle titleStyle, textStyle;
        Font font;
        Material floorMaterial, wallMaterial, lineMaterial;
        static bool? chosenTeam;
        bool teamAvatar;
        bool recording;
        float recordingStart;

        async void Start()
        {
            Application.targetFrameRate = 120;
            QualitySettings.vSyncCount = 0;
            QualitySettings.antiAliasing = 4;
            QualitySettings.shadows = ShadowQuality.All;
            QualitySettings.shadowResolution = ShadowResolution.High;
            QualitySettings.shadowDistance = 15;
            Physics.gravity = new Vector3(0, -9.81f, 0);
            Time.fixedDeltaTime = 1f / 60;
            try
            {
                BuildStage();
                string root = Path.Combine(Application.streamingAssetsPath, "DollFight");
                timeline = JsonUtility.FromJson<DuelTimeline>(File.ReadAllText(Path.Combine(root, "duel.json")));
                if (timeline.version != "dollfight-duel-1" || timeline.frames.Length < 2)
                    throw new InvalidDataException("Unsupported duel timeline");
                Actors = new HumanoidReplay[2]; cloth = new NativeClothCage[2];
                worldCameras = new Camera[2]; bodyCameras = new Camera[2];
                string[] names = { "nozomi", "mizore" };
                teamAvatar = chosenTeam ?? !Array.Exists(Environment.GetCommandLineArgs(), a => a == "-dollfightClassic");
                for (int i = 0; i < 2; i++)
                {
                    var rootObject = new GameObject(i == 0 ? "P1 Nozomi" : "P2 Mizore");
                    var actor = rootObject.AddComponent<HumanoidReplay>();
                    actor.externallyDriven = true; actor.playing = false;
                    if (i == 1 && teamAvatar)
                    {
                        var prefab = Resources.Load<GameObject>("TeamCharacter");
                        if (prefab == null) throw new FileNotFoundException("Prepare Team Character in the DollFight menu first");
                        var model = Instantiate(prefab, rootObject.transform);
                        actor.existingHumanoid = model.GetComponent<Animator>();
                    }
                    await actor.LoadAsync(Path.Combine(root, names[i] + ".vrm"),
                        File.ReadAllText(Path.Combine(root, names[i] + "-motion.json")));
                    Actors[i] = actor;
                    // Cloth bind pose must be constructed in the imported rest
                    // pose; the loader initializes at t=0, so restore initial
                    // Transform states while building the physics proxy.
                    actor.RestoreBindPose();
                    if (actor.Instance != null) ApplyLitSurfaces(actor);
                    if (actor.Instance != null)
                    {
                        cloth[i] = rootObject.AddComponent<NativeClothCage>();
                        cloth[i].Initialize(actor, JsonUtility.FromJson<ClothCageData>(
                            File.ReadAllText(Path.Combine(root, names[i] + "-cloth.json"))));
                    }
                    actor.Apply(0);
                    worldCameras[i] = MakeCamera($"Player {i + 1} opponent", 70, 2 + i * 2);
                    bodyCameras[i] = MakeCamera($"Player {i + 1} body", 78, 3 + i * 2);
                    bodyCameras[i].clearFlags = CameraClearFlags.Depth;
                    bodyCameras[i].nearClipPlane = 0.025f;
                    worldCameras[i].cullingMask = MainMask & ~(1 << (8 + i * 2)) & ~(1 << (12 + i));
                    bodyCameras[i].cullingMask = (1 << (9 + i * 2)) | (1 << (12 + i));
                    rootObject.AddComponent<FirstPersonBody>().Initialize(actor, bodyCameras[i], 8 + i * 2, 9 + i * 2);
                }
                Ready = true; status = "Unity / Humanoid / constrained cloth / " + (teamAvatar ? "team FBX + VRM" : "2 VRM");
                Debug.Log("DOLLFIGHT_READY " + status);
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
            if (!Ready) return;
            if (Input.GetKeyDown(KeyCode.Space)) playing = !playing;
            if (Input.GetKeyDown(KeyCode.R)) Seek(0);
            if (Input.GetKeyDown(KeyCode.V)) showPlayerViews = !showPlayerViews;
            if (Input.GetKeyDown(KeyCode.H)) showSelf = !showSelf;
            if (Input.GetKeyDown(KeyCode.T)) SwitchAvatar();
            if (playing) time = recording ? Mathf.Min(Time.realtimeSinceStartup - recordingStart, timeline.duration - 0.001f) : Mathf.Repeat(time + Time.deltaTime * speed, timeline.duration);
            bool jumped = time < lastTime || Mathf.Abs(time - lastTime) > 0.2f;
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
        }

        public void Seek(float seconds) { time = Mathf.Clamp(seconds, 0, timeline.duration - 0.001f); }

        void SwitchAvatar()
        {
            chosenTeam = !teamAvatar;
            UnityEngine.SceneManagement.SceneManager.LoadScene(UnityEngine.SceneManagement.SceneManager.GetActiveScene().name);
        }

        void UpdateCameras()
        {
            MainCamera.rect = showPlayerViews ? new Rect(0, 0.32f, 1, 0.68f) : new Rect(0, 0, 1, 1);
            for (int i = 0; i < 2; i++)
            {
                var head = Actors[i].Bones[4].position;
                var ownHip = Actors[i].Bones[0].position;
                var opponent = Actors[1 - i].Bones[0].position;
                Vector3 forward = opponent - ownHip; forward.y = 0; forward.Normalize();
                Rect rect = new Rect(i * 0.5f, 0, 0.5f, 0.32f);
                var world = worldCameras[i]; var body = bodyCameras[i];
                world.enabled = showPlayerViews; body.enabled = showPlayerViews && showSelf;
                world.rect = body.rect = rect;
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
            RenderSettings.ambientMode = AmbientMode.Trilight;
            RenderSettings.ambientSkyColor = new Color(0.65f, 0.72f, 0.85f);
            RenderSettings.ambientEquatorColor = new Color(0.42f, 0.48f, 0.56f);
            RenderSettings.ambientGroundColor = new Color(0.25f, 0.29f, 0.34f);
            floorMaterial = Surface(new Color(0.11f, 0.15f, 0.19f));
            wallMaterial = Surface(new Color(0.065f, 0.09f, 0.13f));
            lineMaterial = new Material(lineShader) { color = new Color(0.16f, 0.35f, 0.39f) };
            Primitive("Arena floor", PrimitiveType.Cube, new Vector3(0, -0.075f, 0), new Vector3(14, 0.15f, 12), floorMaterial);
            Primitive("Backdrop", PrimitiveType.Cube, new Vector3(0, 2, -3.2f), new Vector3(14, 4, 0.15f), wallMaterial);
            for (int i = -7; i <= 7; i++)
            {
                Primitive("Floor line", PrimitiveType.Cube, new Vector3(i * 0.5f, 0.002f, 0), new Vector3(0.006f, 0.003f, 8), lineMaterial);
                Primitive("Floor line", PrimitiveType.Cube, new Vector3(0, 0.002f, i * 0.5f), new Vector3(10, 0.003f, 0.006f), lineMaterial);
            }
            for (int i = -4; i <= 4; i++)
                Primitive("Backdrop strip", PrimitiveType.Cube, new Vector3(i * 1.1f, 1.8f, -3.1f), new Vector3(0.025f, 3.2f, 0.025f), lineMaterial);
            var key = new GameObject("Soft key light").AddComponent<Light>();
            key.type = LightType.Directional; key.intensity = 1.25f;
            key.transform.rotation = Quaternion.Euler(42, -25, 0);
            key.shadows = LightShadows.Soft; key.shadowStrength = 0.65f;
            key.shadowBias = 0.005f; key.shadowNormalBias = 0.015f;
            var fill = new GameObject("Fill light").AddComponent<Light>();
            fill.type = LightType.Directional; fill.intensity = 0.45f;
            fill.transform.rotation = Quaternion.Euler(25, 150, 0);
            MainCamera = MakeCamera("Main arena camera", 43, 0);
            MainCamera.transform.position = new Vector3(1.8f, 1.8f, 4.3f);
            MainCamera.transform.LookAt(new Vector3(0, 0.83f, 0));
            MainCamera.gameObject.AddComponent<AudioListener>();
        }

        Material Surface(Color color)
        {
            var material = new Material(stageShader) { color = color };
            material.SetFloat("_Glossiness", 0.22f); return material;
        }
        void Primitive(string label, PrimitiveType kind, Vector3 position, Vector3 scale, Material material)
        {
            var go = GameObject.CreatePrimitive(kind); go.name = label;
            go.transform.position = position; go.transform.localScale = scale;
            go.GetComponent<Renderer>().sharedMaterial = material;
        }

        void OnGUI()
        {
            float factor = Screen.width / 1280f;
            GUI.matrix = Matrix4x4.Scale(new Vector3(factor, factor, 1));
            float height = Screen.height / factor;
            if (titleStyle == null)
            {
                font = Font.CreateDynamicFontFromOSFont(new[] { "Microsoft YaHei", "Arial" }, 20);
                titleStyle = new GUIStyle(GUI.skin.label) { font = font, fontSize = 23, fontStyle = FontStyle.Bold };
                textStyle = new GUIStyle(GUI.skin.label) { font = font, fontSize = 17 };
            }
            GUI.Box(new Rect(0, 0, 1280, 95), GUIContent.none);
            var frame = Ready ? timeline.frames[Mathf.Clamp(Mathf.FloorToInt(time * timeline.fps), 0, timeline.frames.Length - 1)] : null;
            GUI.Label(new Rect(22, 10, 540, 32), $"DOLLFIGHT  /  UNITY   ROUND {frame?.round ?? 1} / 3", titleStyle);
            GUI.Label(new Rect(620, 13, 640, 28), $"{time:0.0} / 90 s  ·  {frame?.intent ?? status}", textStyle);
            GUI.Label(new Rect(24, 55, 280, 28), $"P1  NOZOMI    {frame?.health[0] ?? 100:0} HP", textStyle);
            GUI.Label(new Rect(520, 55, 250, 28), $"{frame?.distance ?? 1.8f:0.00} m   /   {fps:0} FPS", textStyle);
            GUI.Label(new Rect(980, 55, 280, 28), $"P2  {(teamAvatar ? "TEAM FBX" : "MIZORE")}    {frame?.health[1] ?? 100:0} HP", textStyle);
            float barY = showPlayerViews ? height * 0.68f - 38 : height - 42;
            GUI.Label(new Rect(22, barY - 38, 900, 28), "真人动捕编辑排练 · 非实时相机采集", textStyle);
            GUI.Box(new Rect(0, barY - 7, 1280, 46), GUIContent.none);
            if (GUI.Button(new Rect(16, barY, 85, 28), playing ? "Pause" : "Play")) playing = !playing;
            if (GUI.Button(new Rect(112, barY, 65, 28), "Reset")) Seek(0);
            if (Ready)
            {
                float next = GUI.HorizontalSlider(new Rect(195, barY + 10, 560, 20), time, 0, timeline.duration - 0.001f);
                if (Mathf.Abs(next - time) > 0.001f) Seek(next);
            }
            if (GUI.Button(new Rect(780, barY, 70, 28), $"{speed:0.##}x")) speed = speed == 1 ? 0.25f : speed == 0.25f ? 0.5f : 1;
            showSelf = GUI.Toggle(new Rect(870, barY + 4, 100, 25), showSelf, "Own body");
            showPlayerViews = GUI.Toggle(new Rect(985, barY + 4, 120, 25), showPlayerViews, "Player views");
            if (GUI.Button(new Rect(1110, barY, 155, 28), teamAvatar ? "T: compare VRM" : "T: team model")) SwitchAvatar();
            if (showPlayerViews)
            {
                GUI.Label(new Rect(22, height * 0.68f + 8, 580, 30), "PLAYER 1  /  opponent + own body", textStyle);
                GUI.Label(new Rect(662, height * 0.68f + 8, 580, 30), "PLAYER 2  /  opponent + own body", textStyle);
            }
        }

        static string CommandValue(string name)
        {
            string[] args = Environment.GetCommandLineArgs();
            int index = Array.IndexOf(args, name);
            return index >= 0 && index + 1 < args.Length ? args[index + 1] : null;
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
            Seek(0); playing = true; speed = 1; showPlayerViews = true; showSelf = true;
            var samples = new System.Collections.Generic.List<float>(12000);
            int invalid = 0;
            float elapsed = 0;
            while (elapsed < 90)
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
                avatars = teamAvatar ? "Nozomi hybrid VRM + team FBX" : "Nozomi + Mizore hybrid VRM",
                width = Screen.width, height = Screen.height, frames = samples.Count,
                invalidBoneFrames = invalid, durationSeconds = elapsed,
                averageFps = samples.Count / elapsed,
                medianFrameMs = samples[samples.Count / 2],
                p95FrameMs = samples[Mathf.Min(samples.Count - 1, Mathf.FloorToInt(samples.Count * 0.95f))],
                maxFrameMs = samples[samples.Count - 1],
                note = "90 seconds, 3 views plus 2 own-limb overlays and view-only IK; original meshes; guided native cloth and VRM springs; target 120 fps; not camera-input latency."
            };
            Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(path)));
            File.WriteAllText(path, JsonUtility.ToJson(result, true));
            Debug.Log("DOLLFIGHT_BENCHMARK_COMPLETE " + path);
        }

        IEnumerator RecordReview(string folder)
        {
            Directory.CreateDirectory(folder);
            playing = false; Seek(0);
            string ffmpeg = CommandValue("-dollfightFfmpeg");
            NativeReviewRecorder recorder = null;
            float duration = timeline.duration;
            if (float.TryParse(CommandValue("-dollfightRecordSeconds"),
                System.Globalization.NumberStyles.Float, System.Globalization.CultureInfo.InvariantCulture, out float limit))
                duration = Mathf.Clamp(limit, 1, duration);
            if (!string.IsNullOrEmpty(ffmpeg))
                recorder = new NativeReviewRecorder(ffmpeg, Path.Combine(folder, "review.mp4"), Screen.width, Screen.height);
            File.WriteAllText(Path.Combine(folder, "ready.txt"), status);
            if (recorder == null)
                while (!File.Exists(Path.Combine(folder, "start.txt"))) yield return null;
            // Wait out the first loading frame; its large deltaTime must not
            // advance the clip before recording has actually begun.
            yield return new WaitForEndOfFrame();
            recorder?.Capture(0);
            recording = true; playing = true; speed = 1; Seek(0);
            float begin = recordingStart = Time.realtimeSinceStartup;
            int frames = Mathf.CeilToInt(duration * 30);
            var endOfFrame = new WaitForEndOfFrame();
            while (time < duration - 0.002f)
            {
                yield return endOfFrame;
                recorder?.Capture(Mathf.Min(frames - 1, Mathf.FloorToInt(time * 30)));
                if (recorder?.Error != null) break;
            }
            playing = false; recording = false;
            float elapsed = Time.realtimeSinceStartup - begin;
            if (recorder != null)
            {
                while (recorder.Pending) yield return null;
                recorder.Finish(frames);
                while (!recorder.Complete) yield return null;
                string error = recorder.Error;
                File.WriteAllText(Path.Combine(folder, "capture.json"),
                    "{\"capturedFrames\":" + recorder.CapturedFrames + ",\"repeatedFrames\":" + recorder.RepeatedFrames + "}");
                recorder.Dispose();
                if (error != null) { File.WriteAllText(Path.Combine(folder, "error.txt"), error); yield break; }
            }
            File.WriteAllText(Path.Combine(folder, "complete.json"),
                "{\"replaySeconds\":" + duration.ToString(System.Globalization.CultureInfo.InvariantCulture) +
                ",\"wallSeconds\":" + elapsed.ToString(System.Globalization.CultureInfo.InvariantCulture) + "}");
        }

        void OnDestroy()
        {
            if (floorMaterial != null) Destroy(floorMaterial);
            if (wallMaterial != null) Destroy(wallMaterial);
            if (lineMaterial != null) Destroy(lineMaterial);
            if (font != null) Destroy(font);
        }
    }
}
