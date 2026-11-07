using System.Collections;
using GaussianSplatting.Runtime;
using UnityEngine;
using UnityEngine.Rendering;

namespace DollFight.Environments
{
    /// <summary>The supplied floating rune platform, aligned to the unchanged combat floor.</summary>
    public sealed class CloudEnvironment : MonoBehaviour
    {
        public GaussianSplatRenderer scan;
        public DollFightDemo duel;
        public Vector3 duelCameraPosition = new(0, 2.5f, -5.1f);
        public Vector3 duelCameraTarget = new(0, 0.95f, 0);
        public float duelCameraFieldOfView = 46;
        string status = "Loading cloud platform...";
        GUIStyle statusStyle;

        void Awake()
        {
            QualitySettings.antiAliasing = 0;
            Application.runInBackground = true;
            if (duel != null) duel.playing = false;
        }

        IEnumerator Start()
        {
            if (scan == null)
            {
                status = "Cloud scan renderer is missing";
                Debug.LogError("CLOUD_LOAD_FAILED " + status);
                yield break;
            }
            while (scan.isLoading || !scan.HasValidRenderSetup || (duel != null && !duel.Ready))
            {
                if (!string.IsNullOrEmpty(scan.loadError))
                {
                    status = scan.loadError;
                    Debug.LogError("CLOUD_LOAD_FAILED " + status);
                    yield break;
                }
                yield return null;
            }
            if (duel != null)
            {
                BuildCloudLighting();
                var camera = duel.MainCamera;
                camera.transform.SetPositionAndRotation(duelCameraPosition,
                    Quaternion.LookRotation(duelCameraTarget - duelCameraPosition, Vector3.up));
                camera.fieldOfView = duelCameraFieldOfView;
                camera.farClipPlane = 160;
                camera.allowMSAA = false;
                camera.backgroundColor = new Color(0.35f, 0.31f, 0.36f);
                duel.Seek(0);
                // The demo owns playback, including menu and scene transition state.
                duel.MarkEnvironmentReady();
            }
            status = $"{scan.splatCount:N0} splats / SH{scan.sourceSHDegree}";
            Debug.Log($"CLOUD_READY {status} bounds={scan.localBounds} " +
                $"scanPosition={scan.transform.position} scanRotation={scan.transform.rotation} " +
                $"scanScale={scan.transform.localScale}");
        }

        void BuildCloudLighting()
        {
            // Match the bright warm clouds while keeping the inherited key and cool rim.
            // Run after the demo's shared lighting setup, which otherwise supplies the
            // darker church ambient. Gaussian scan colours are already baked in the PLY.
            RenderSettings.ambientMode = AmbientMode.Trilight;
            RenderSettings.ambientSkyColor = new Color(0.48f, 0.47f, 0.48f);
            RenderSettings.ambientEquatorColor = new Color(0.31f, 0.30f, 0.34f);
            RenderSettings.ambientGroundColor = new Color(0.19f, 0.18f, 0.21f);
            var fill = new GameObject("Cloud warm camera-side character fill").AddComponent<Light>();
            fill.transform.SetParent(transform, false);
            fill.transform.localRotation = Quaternion.Euler(12, 0, 0);
            fill.type = LightType.Directional;
            fill.color = new Color(1, 0.91f, 0.79f);
            fill.intensity = 0.62f;
            fill.shadows = LightShadows.None;
            fill.renderMode = LightRenderMode.ForcePixel;
            fill.cullingMask = (1 << 8) | (1 << 10) | (1 << 12) | (1 << 13);
        }

        void OnGUI()
        {
            if (duel != null && duel.SelectionOpen) return;
            if (scan != null && scan.HasValidRenderSetup) return;
            Matrix4x4 previousMatrix = GUI.matrix;
            Color previousColor = GUI.color;
            try
            {
                GUI.matrix = Matrix4x4.identity;
                GUI.color = Color.white;
                statusStyle ??= new GUIStyle(GUI.skin.label) { fontSize = 16, wordWrap = true };
                GUI.Label(new Rect(24, 120, Screen.width - 48, 90), "Cloud: " + status, statusStyle);
            }
            finally
            {
                GUI.matrix = previousMatrix;
                GUI.color = previousColor;
            }
        }
    }
}
