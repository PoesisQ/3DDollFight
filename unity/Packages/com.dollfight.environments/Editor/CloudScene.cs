using System.IO;
using GaussianSplatting.Runtime;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

namespace DollFight.Environments.Editor
{
    public static class CloudScene
    {
        public const string SplatPath = "Environments/Cloud/cloud.spz";
        public const string DuelPath = "Assets/Scenes/CloudDuel.unity";

        // Reproduce data/environments/cloud.json. SPZ coordinates are unchanged from PLY.
        // Source Y reflection plus -90 degrees around X maps source Z up to Unity Y up.
        // Then remove the fitted top surface's 3.72 degree tilt and center the larger disk.
        public static readonly Vector3 SourceOrigin = new(1.6f, -2.3f, -0.49210526f);
        public static readonly Vector3 ScanScale = new(1.75f, -1.75f, 1.75f);
        public static Quaternion ScanRotation =>
            Quaternion.FromToRotation(new Vector3(0.02653103f, 0.99789697f, -0.05914176f), Vector3.up)
            * Quaternion.Euler(-90, 0, 0);
        public static Vector3 ScanPosition => -(ScanRotation * Vector3.Scale(SourceOrigin, ScanScale));

        [MenuItem("DollFight/Cloud/Create Cloud Duel")]
        public static void CreateDuel()
        {
            string splat = Path.Combine(Application.streamingAssetsPath, SplatPath);
            if (!File.Exists(splat)) throw new FileNotFoundException("Run tools/prepare_cloud.py first", splat);
            if (!Application.isBatchMode && !EditorSceneManager.SaveCurrentModifiedScenesIfUserWantsTo()) return;
            EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
            QualitySettings.antiAliasing = 0;
            new GameObject("Gaussian render options").AddComponent<GaussianSplatRenderingOptions>();
            var environment = new GameObject("Cloud platform environment").AddComponent<CloudEnvironment>();
            var scanObject = new GameObject("Cloud rune platform (complete user scan)");
            scanObject.SetActive(false);
            scanObject.transform.SetParent(environment.transform, false);
            scanObject.transform.SetLocalPositionAndRotation(ScanPosition, ScanRotation);
            scanObject.transform.localScale = ScanScale;
            var scan = scanObject.AddComponent<GaussianSplatRenderer>();
            scan.m_SourcePath = SplatPath;
            scan.m_SHOrder = 0;
            environment.scan = scan;
            scanObject.SetActive(true);

            var demo = new GameObject("DollFight Demo").AddComponent<DollFightDemo>();
            demo.createDefaultEnvironment = false;
            demo.useMsaa = false;
            demo.stageShader = Shader.Find("Standard");
            demo.lineShader = Shader.Find("Unlit/Color");
            environment.duel = demo;

            // Invisible collision only. All four box corners lie inside the gold disk's
            // measured safe interior (2.1 m radius); no authored floor covers its texture.
            var floor = new GameObject("Measured rune platform floor collider").AddComponent<BoxCollider>();
            floor.transform.SetParent(environment.transform, false);
            floor.center = new Vector3(0, -0.1f, 0);
            floor.size = new Vector3(3.2f, 0.2f, 2.6f);

            EditorSceneManager.SaveScene(UnityEngine.SceneManagement.SceneManager.GetActiveScene(), DuelPath);
            AssetDatabase.SaveAssets();
            Debug.Log($"CLOUD_SCENE_CREATED {DuelPath} position={ScanPosition} rotation={ScanRotation}");
        }

        [MenuItem("DollFight/Cloud/Open Cloud Duel")]
        public static void OpenDuel()
        {
            if (!File.Exists(DuelPath)) CreateDuel();
            else
            {
                if (!Application.isBatchMode && !EditorSceneManager.SaveCurrentModifiedScenesIfUserWantsTo()) return;
                EditorSceneManager.OpenScene(DuelPath);
            }
        }
    }
}
