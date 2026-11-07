using System;
using System.IO;
using GaussianSplatting.Runtime;
using UnityEditor;
using UnityEditor.Build.Reporting;
using UnityEditor.SceneManagement;
using UnityEngine;

namespace DollFight.Environments.Editor
{
    public static class SaintMauriceScene
    {
        public const string SourcePath = "Assets/StreamingAssets/Environments/SaintMaurice/source.sog";
        public const string SplatPath = "Environments/SaintMaurice/church.spz";
        public const string FullSplatPath = "Assets/LocalScenes/SaintMaurice/church-full.spz";
        public const string PreviewPath = "Assets/Scenes/SaintMauricePreview.unity";
        public const string DuelPath = "Assets/Scenes/SaintMauriceDuel.unity";

        [MenuItem("DollFight/Saint Maurice/Inspect SOG Import")]
        public static void InspectSource()
        {
            bool temporary = !File.Exists(SourcePath);
            if (temporary)
            {
                string source = Path.GetFullPath(Path.Combine(Application.dataPath, "../../../Parish Church of Saint Maurice.sog"));
                Directory.CreateDirectory(Path.GetDirectoryName(SourcePath));
                File.Copy(source, SourcePath);
            }
            AssetDatabase.ImportAsset(SourcePath, ImportAssetOptions.ForceSynchronousImport);
            var importer = AssetImporter.GetAtPath(SourcePath);
            var asset = AssetDatabase.LoadMainAssetAtPath(SourcePath);
            string report = $"Source: {SourcePath}\nImporter: {importer?.GetType().FullName}\nAsset type: {asset?.GetType().FullName}\n";
            string directory = Output("import");
            Directory.CreateDirectory(directory);
            File.WriteAllText(Path.Combine(directory, "sog-import.txt"), report);
            Debug.Log("SAINT_MAURICE_SOG_PROBE " + report);
            if (temporary) AssetDatabase.DeleteAsset(SourcePath);
        }

        [MenuItem("DollFight/Saint Maurice/Create Scan Preview")]
        public static void CreatePreview() => Create(false);

        [MenuItem("DollFight/Saint Maurice/Create Church Duel")]
        public static void CreateDuel() => Create(true);

        [MenuItem("DollFight/Saint Maurice/Open Church Duel")]
        public static void OpenDuel()
        {
            if (!File.Exists(DuelPath)) CreateDuel();
            else
            {
                if (!Application.isBatchMode && !EditorSceneManager.SaveCurrentModifiedScenesIfUserWantsTo()) return;
                EditorSceneManager.OpenScene(DuelPath);
            }
        }

        static void Create(bool withDuel)
        {
            string splat = withDuel ? Path.Combine(Application.streamingAssetsPath, SplatPath) : Path.GetFullPath(FullSplatPath);
            if (!File.Exists(splat)) throw new FileNotFoundException("Prepare the local church SPZ first", splat);
            if (!Application.isBatchMode && !EditorSceneManager.SaveCurrentModifiedScenesIfUserWantsTo()) return;
            EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
            QualitySettings.antiAliasing = 0;
            new GameObject("Gaussian render options").AddComponent<GaussianSplatRenderingOptions>();
            var environment = new GameObject("Saint Maurice environment").AddComponent<ChurchEnvironment>();
            var scanObject = new GameObject("Parish Church of Saint Maurice (Gaussian scan)");
            scanObject.SetActive(false);
            scanObject.transform.SetParent(environment.transform);
            scanObject.transform.localScale = new Vector3(1, -1, 1);
            scanObject.transform.localPosition = withDuel ? new Vector3(0, 2.05f, -1) : new Vector3(0, 2, 0);
            var scan = scanObject.AddComponent<GaussianSplatRenderer>();
            scan.m_SourcePath = withDuel ? SplatPath : FullSplatPath;
            scan.m_SHOrder = withDuel ? 1 : 3;
            environment.scan = scan;
            scanObject.SetActive(true);
            if (withDuel)
            {
                var demo = new GameObject("DollFight Demo").AddComponent<DollFightDemo>();
                demo.createDefaultEnvironment = false;
                demo.useMsaa = false;
                demo.stageShader = Shader.Find("Standard");
                demo.lineShader = Shader.Find("Unlit/Color");
                environment.duel = demo;
                var ground = new GameObject("Combat floor collider").AddComponent<BoxCollider>();
                ground.center = new Vector3(0, -0.1f, 0);
                ground.size = new Vector3(6, 0.2f, 2);
                foreach (float side in new[] { -1f, 1f })
                {
                    var lateral = new GameObject("Combat side boundary").AddComponent<BoxCollider>();
                    lateral.center = new Vector3(side * 3, 1, 0);
                    lateral.size = new Vector3(0.15f, 2, 2);
                    var end = new GameObject("Combat depth boundary").AddComponent<BoxCollider>();
                    end.center = new Vector3(0, 1, side);
                    end.size = new Vector3(6, 2, 0.15f);
                }
            }
            else
            {
                var camera = new GameObject("Main Camera").AddComponent<Camera>();
                camera.tag = "MainCamera";
                camera.transform.position = new Vector3(0, 1.6f, 0);
                camera.fieldOfView = 75;
                camera.nearClipPlane = 0.03f;
                camera.farClipPlane = 200;
                camera.clearFlags = CameraClearFlags.SolidColor;
                camera.backgroundColor = new Color(0.07f, 0.07f, 0.07f);
                camera.allowMSAA = false;
                camera.gameObject.AddComponent<AudioListener>();
                environment.previewCamera = camera;
            }
            string scenePath = withDuel ? DuelPath : PreviewPath;
            EditorSceneManager.SaveScene(UnityEngine.SceneManagement.SceneManager.GetActiveScene(), scenePath);
            AssetDatabase.SaveAssets();
            Debug.Log("SAINT_MAURICE_SCENE_CREATED " + scenePath);
        }

        [MenuItem("DollFight/Saint Maurice/Build Church Duel")]
        public static void BuildDuel() => Build(DuelPath, "duel");

        static void Build(string scene, string name)
        {
            if (!Application.isBatchMode && !EditorSceneManager.SaveCurrentModifiedScenesIfUserWantsTo()) return;
            if (!File.Exists(scene)) throw new FileNotFoundException("Create the church scene first", scene);
            var scenes = new[] { scene, "Assets/Scenes/DollFight.unity", "Assets/Scenes/CloudDuel.unity" };
            foreach (string stageScene in scenes)
                if (!File.Exists(stageScene)) throw new FileNotFoundException("Create every selection stage before building", stageScene);
            EditorBuildSettings.scenes = Array.ConvertAll(scenes, stagePath => new EditorBuildSettingsScene(stagePath, true));
            PlayerSettings.SetUseDefaultGraphicsAPIs(BuildTarget.StandaloneWindows64, false);
            PlayerSettings.SetGraphicsAPIs(BuildTarget.StandaloneWindows64, new[] { UnityEngine.Rendering.GraphicsDeviceType.Direct3D12 });
            string path = Output(name + "/DollFightChurch.exe");
            Directory.CreateDirectory(Path.GetDirectoryName(path));
            var report = BuildPipeline.BuildPlayer(new BuildPlayerOptions
            {
                scenes = scenes, locationPathName = path,
                target = BuildTarget.StandaloneWindows64, options = BuildOptions.None
            });
            if (report.summary.result != BuildResult.Succeeded) throw new InvalidOperationException("Church build failed");
            Debug.Log("SAINT_MAURICE_BUILD_OK " + path);
        }

        static string Output(string path) => Path.GetFullPath(Path.Combine(Application.dataPath, "../../outputs/saint-maurice", path));
    }
}
