using System;
using System.Collections;
using System.IO;
using GaussianSplatting.Runtime;
using UnityEngine;

namespace DollFight.Environments
{
    public sealed class ChurchEnvironment : MonoBehaviour
    {
        public GaussianSplatRenderer scan;
        public DollFightDemo duel;
        public Camera previewCamera;
        public Vector3 duelCameraPosition = new(0, 2.2f, -3.5f);
        public Vector3 duelCameraTarget = new(0, 0.83f, 0);
        public const string Credit = "Parish Church of Saint Maurice · Pavel Tanhäuser · CC BY-NC-ND 4.0";
        string status = "Loading church scan...";
        GUIStyle creditStyle;

        [Serializable]
        sealed class ReviewMetrics
        {
            public string device, graphicsApi, avatars;
            public int points, sourceSH, renderedSH, width, height, frames, invalidBoneFrames, views;
            public float durationSeconds, averageFps, p95FrameMs;
        }

        void Awake()
        {
            QualitySettings.antiAliasing = 0;
            Application.runInBackground = true;
            if (duel != null) duel.playing = false;
        }

        IEnumerator Start()
        {
            while (scan != null && (scan.isLoading || !scan.HasValidRenderSetup || (duel != null && !duel.Ready)))
            {
                if (!string.IsNullOrEmpty(scan.loadError))
                {
                    status = scan.loadError;
                    Debug.LogError("SAINT_MAURICE_LOAD_FAILED " + status);
                    yield break;
                }
                yield return null;
            }
            if (scan == null) yield break;
            if (duel != null)
            {
                duel.MainCamera.transform.position = duelCameraPosition;
                // Leave clear space for the tall hat beneath the combat HUD.
                // Apply once to the baseline; shake is restored separately each frame.
                duel.MainCamera.transform.LookAt(duelCameraTarget + Vector3.up * 0.35f);
                duel.Seek(0);
                duel.MarkEnvironmentReady();
            }
            status = $"{scan.splatCount:N0} splats / SH{scan.sourceSHDegree}";
            Debug.Log($"SAINT_MAURICE_READY {status} bounds={scan.localBounds}");
            string review = Argument("-churchReview");
            if (!string.IsNullOrEmpty(review)) yield return Review(review);
        }

        IEnumerator Review(string directory)
        {
            Directory.CreateDirectory(directory);
            for (int i = 0; i < 45; i++) yield return null;
            if (duel == null && previewCamera != null)
            {
                Vector3[] angles = { Vector3.zero, new(0, 90, 0), new(0, 180, 0), new(0, 270, 0), new(-65, 0, 0), new(65, 0, 0) };
                for (int index = 0; index < angles.Length; index++)
                {
                    previewCamera.transform.rotation = Quaternion.Euler(angles[index]);
                    for (int frame = 0; frame < 8; frame++) yield return null;
                    yield return new WaitForEndOfFrame();
                    ScreenCapture.CaptureScreenshot(Path.Combine(directory, $"preview-{index}.png"));
                    yield return null;
                }
                previewCamera.transform.rotation = Quaternion.identity;
            }
            else if (duel != null)
            {
                duel.playing = false;
                foreach (float seconds in new[] { 4.1f, 13.7f, 84.2f })
                {
                    duel.Seek(seconds);
                    for (int frame = 0; frame < 30; frame++) yield return null;
                    yield return new WaitForEndOfFrame();
                    ScreenCapture.CaptureScreenshot(Path.Combine(directory, $"duel-{seconds:00.0}.png"));
                    yield return null;
                }
                duel.Seek(0);
                duel.playing = true;
            }
            float secondsToMeasure = 12;
            if (float.TryParse(Argument("-churchReviewSeconds"), System.Globalization.NumberStyles.Float,
                    System.Globalization.CultureInfo.InvariantCulture, out float requested))
                secondsToMeasure = Mathf.Clamp(requested, 3, 90);
            float elapsed = 0;
            int invalid = 0;
            var frameTimes = new System.Collections.Generic.List<float>();
            while (elapsed < secondsToMeasure)
            {
                yield return null;
                float delta = Time.unscaledDeltaTime;
                elapsed += delta;
                frameTimes.Add(delta * 1000);
                bool bad = false;
                if (duel != null && duel.Ready)
                    foreach (var actor in duel.Actors)
                        foreach (var bone in actor.Bones)
                            if (!float.IsFinite(bone.position.sqrMagnitude)) bad = true;
                if (bad) invalid++;
            }
            frameTimes.Sort();
            var metrics = new ReviewMetrics
            {
                device = SystemInfo.graphicsDeviceName, graphicsApi = SystemInfo.graphicsDeviceType.ToString(),
                avatars = duel == null ? "scan only" : duel.Actors[1].existingHumanoid != null ? "VRM + team FBX" : "two VRMs",
                points = scan.splatCount, sourceSH = scan.sourceSHDegree, renderedSH = scan.m_SHOrder,
                width = Screen.width, height = Screen.height, frames = frameTimes.Count, invalidBoneFrames = invalid,
                views = duel == null || !duel.showPlayerViews ? 1 : 3, durationSeconds = elapsed, averageFps = frameTimes.Count / elapsed,
                p95FrameMs = frameTimes[Mathf.Min(frameTimes.Count - 1, Mathf.FloorToInt(frameTimes.Count * 0.95f))]
            };
            File.WriteAllText(Path.Combine(directory, "performance.json"), JsonUtility.ToJson(metrics, true));
            File.WriteAllText(Path.Combine(directory, "ready.txt"), status);
            Debug.Log("SAINT_MAURICE_REVIEW_COMPLETE " + directory);
        }

        static string Argument(string name)
        {
            string[] args = Environment.GetCommandLineArgs();
            int index = Array.IndexOf(args, name);
            return index >= 0 && index + 1 < args.Length ? args[index + 1] : null;
        }

        void OnGUI()
        {
            if (duel != null && duel.SelectionOpen) return;
            Matrix4x4 previousMatrix = GUI.matrix;
            Color previousColor = GUI.color;
            GUIStyle label = GUI.skin.label;
            try
            {
                GUI.matrix = Matrix4x4.identity;
                if (creditStyle == null)
                    creditStyle = new GUIStyle(label)
                    {
                        fontSize = 11,
                        fontStyle = FontStyle.Normal,
                        alignment = TextAnchor.MiddleLeft
                    };
                if (duel != null)
                {
                    Rect arena = DollFight.DuelPresentationLayout.Arena(Screen.width, Screen.height);
                    float scale = arena.width / 1440f;
                    creditStyle.fontSize = Mathf.Max(8, Mathf.RoundToInt(11 * scale));
                    GUI.Label(new Rect(arena.x + 34 * scale, arena.yMax - 18 * scale,
                        arena.width - 68 * scale, 16 * scale), Credit, creditStyle);
                }
                else
                    GUI.Label(new Rect(12, Screen.height - 24, Screen.width - 24, 16), Credit, creditStyle);
                if (scan == null || !scan.HasValidRenderSetup)
                    GUI.Label(new Rect(20, 115, Screen.width - 40, 45), "Church: " + status);
            }
            finally
            {
                GUI.matrix = previousMatrix;
                GUI.color = previousColor;
            }
        }
    }
}
