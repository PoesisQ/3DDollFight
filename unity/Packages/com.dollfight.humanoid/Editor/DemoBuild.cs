using System;
using System.IO;
using UnityEditor;
using UnityEditor.Build.Reporting;
using UnityEditor.SceneManagement;
using UnityEngine;

namespace DollFight.Editor
{
    public static class DemoBuild
    {
        public const string ScenePath = "Assets/Scenes/DollFight.unity";

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
            EditorBuildSettings.scenes = new[] { new EditorBuildSettingsScene(ScenePath, true) };
            EditorSettings.serializationMode = SerializationMode.ForceText;
            EditorSettings.externalVersionControl = "Visible Meta Files";
            PlayerSettings.companyName = "3DDollFight";
            PlayerSettings.productName = "DollFight Unity";
            PlayerSettings.bundleVersion = "0.10.0";
            PlayerSettings.colorSpace = ColorSpace.Linear;
            PlayerSettings.defaultScreenWidth = 1280;
            PlayerSettings.defaultScreenHeight = 1000;
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
            string output = Path.GetFullPath(Path.Combine(Application.dataPath, "../../outputs/unity-build/DollFight.exe"));
            Directory.CreateDirectory(Path.GetDirectoryName(output));
            BuildReport report = BuildPipeline.BuildPlayer(new BuildPlayerOptions
            {
                scenes = new[] { ScenePath }, locationPathName = output,
                target = BuildTarget.StandaloneWindows64, options = BuildOptions.Development
            });
            if (report.summary.result != BuildResult.Succeeded)
                throw new InvalidOperationException("Unity build failed: " + report.summary.result);
            Debug.Log("DOLLFIGHT_BUILD_OK " + output);
        }
    }
}
