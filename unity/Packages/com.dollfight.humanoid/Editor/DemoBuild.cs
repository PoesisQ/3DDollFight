using System;
using System.IO;
using UnityEditor;
using UnityEditor.Build.Reporting;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Rendering;

namespace DollFight.Editor
{
    public static class DemoBuild
    {
        public const string ScenePath = "Assets/Scenes/DollFight.unity";
        public static readonly string[] MatchScenes = { ScenePath, "Assets/Scenes/SaintMauriceDuel.unity", "Assets/Scenes/CloudDuel.unity" };

        public static void OpenScene()
        {
            if (!File.Exists(ScenePath)) { CreateScene(); return; }
            if (!Application.isBatchMode && !EditorSceneManager.SaveCurrentModifiedScenesIfUserWantsTo()) return;
            EditorSceneManager.OpenScene(ScenePath, OpenSceneMode.Single);
        }

        [MenuItem("DollFight/Create Duel Demo Scene")]
        public static void CreateScene()
        {
            if (!Application.isBatchMode && !EditorSceneManager.SaveCurrentModifiedScenesIfUserWantsTo()) return;
            if (!File.Exists(Path.Combine(Application.streamingAssetsPath, "DollFight/duel.json")))
                throw new FileNotFoundException("First run: uv run --locked python tools/prepare_unity.py");
            Directory.CreateDirectory("Assets/Scenes");
            EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
            var demo = new GameObject("DollFight Demo").AddComponent<DollFightDemo>();
            // Serialized references keep runtime-created materials' shaders
            // in standalone builds; Shader.Find alone gets stripped.
            demo.stageShader = Shader.Find("Standard");
            demo.lineShader = Shader.Find("Unlit/Color");
            if (demo.stageShader == null || demo.lineShader == null)
                throw new InvalidOperationException("Required built-in shaders are missing");
            // Runtime VRM imports have no material assets in the scene for
            // the build pipeline to discover. Preserve their shader variants.
            var graphics = new SerializedObject(AssetDatabase.LoadAllAssetsAtPath("ProjectSettings/GraphicsSettings.asset")[0]);
            var included = graphics.FindProperty("m_AlwaysIncludedShaders");
            foreach (string shaderName in new[] { "VRM10/MToon10", "UniGLTF/UniUnlit" })
            {
                var shader = Shader.Find(shaderName);
                if (shader == null) throw new InvalidOperationException("Missing VRM shader: " + shaderName);
                bool exists = false;
                for (int i = 0; i < included.arraySize; i++)
                    if (included.GetArrayElementAtIndex(i).objectReferenceValue == shader) exists = true;
                if (!exists)
                {
                    int index = included.arraySize++;
                    included.GetArrayElementAtIndex(index).objectReferenceValue = shader;
                }
            }
            graphics.ApplyModifiedPropertiesWithoutUndo();
            EditorSceneManager.SaveScene(UnityEngine.SceneManagement.SceneManager.GetActiveScene(), ScenePath);
            EditorBuildSettings.scenes = Array.ConvertAll(MatchScenes, path => new EditorBuildSettingsScene(path, true));
            EditorSettings.serializationMode = SerializationMode.ForceText;
            EditorSettings.externalVersionControl = "Visible Meta Files";
            PlayerSettings.companyName = "3DDollFight";
            PlayerSettings.productName = "DollFight Unity";
            PlayerSettings.bundleVersion = "0.10.0";
            PlayerSettings.colorSpace = ColorSpace.Linear;
            PlayerSettings.defaultScreenWidth = 1440;
            PlayerSettings.defaultScreenHeight = 900;
            PlayerSettings.fullScreenMode = FullScreenMode.Windowed;
            PlayerSettings.runInBackground = true;
            PlayerSettings.resizableWindow = true;
            PlayerSettings.SetScriptingBackend(UnityEditor.Build.NamedBuildTarget.Standalone, ScriptingImplementation.Mono2x);
            AssetDatabase.SaveAssets();
            AssetDatabase.Refresh();
            Debug.Log("DOLLFIGHT_SCENE_CREATED " + ScenePath);
        }

        [MenuItem("DollFight/Build Windows Demo")]
        public static void BuildWindows()
        {
            // Building an existing project must preserve teammates' scene edits.
            if (!File.Exists(ScenePath)) CreateScene();
            else if (!Application.isBatchMode && !EditorSceneManager.SaveCurrentModifiedScenesIfUserWantsTo()) return;
            foreach (string scene in MatchScenes)
                if (!File.Exists(scene)) throw new FileNotFoundException("Create every selection stage before building", scene);
            EditorBuildSettings.scenes = Array.ConvertAll(MatchScenes, path => new EditorBuildSettingsScene(path, true));
            PlayerSettings.SetUseDefaultGraphicsAPIs(BuildTarget.StandaloneWindows64, false);
            PlayerSettings.SetGraphicsAPIs(BuildTarget.StandaloneWindows64, new[] { GraphicsDeviceType.Direct3D12 });
            var arguments = Environment.GetCommandLineArgs();
            int outputOption = Array.IndexOf(arguments, "-dollfightBuildOutput");
            if (outputOption >= 0 && (outputOption + 1 >= arguments.Length || arguments[outputOption + 1].StartsWith("-", StringComparison.Ordinal)))
                throw new ArgumentException("Missing executable path after -dollfightBuildOutput");
            string output = outputOption >= 0 ? Path.GetFullPath(arguments[outputOption + 1]) :
                Path.GetFullPath(Path.Combine(Application.dataPath, "../../outputs/arcade-select/DollFight.exe"));
            Directory.CreateDirectory(Path.GetDirectoryName(output));
            BuildReport report = BuildPipeline.BuildPlayer(new BuildPlayerOptions
            {
                scenes = MatchScenes, locationPathName = output,
                target = BuildTarget.StandaloneWindows64, options = BuildOptions.None
            });
            if (report.summary.result != BuildResult.Succeeded)
                throw new InvalidOperationException("Unity build failed: " + report.summary.result);
            Debug.Log("DOLLFIGHT_BUILD_OK " + output);
        }
    }
}
