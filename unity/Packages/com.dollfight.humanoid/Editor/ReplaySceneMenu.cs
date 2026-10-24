using System.IO;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

namespace DollFight.Editor
{
    public static class ReplaySceneMenu
    {
        [MenuItem("DollFight/Create VRM Replay Scene")]
        public static void Create()
        {
            string model = EditorUtility.OpenFilePanel("Select local VRM", "", "vrm");
            if (string.IsNullOrEmpty(model)) return;
            string motion = EditorUtility.OpenFilePanel("Select Motion Lab Unity replay", "", "json");
            if (string.IsNullOrEmpty(motion)) return;
            try { HumanoidReplay.ValidateClip(JsonUtility.FromJson<MotionClip>(File.ReadAllText(motion))); }
            catch (System.Exception e) { EditorUtility.DisplayDialog("Invalid replay", e.Message, "Close"); return; }
            if (!EditorSceneManager.SaveCurrentModifiedScenesIfUserWantsTo()) return;
            EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
            if (!AssetDatabase.IsValidFolder("Assets/DollFightReplay")) AssetDatabase.CreateFolder("Assets", "DollFightReplay");
            string path = AssetDatabase.GenerateUniqueAssetPath("Assets/DollFightReplay/replay.json");
            File.Copy(motion, path, false);
            AssetDatabase.ImportAsset(path);
            var player = new GameObject("DollFight VRM Replay").AddComponent<HumanoidReplay>();
            player.vrmPath = model;
            player.replayJson = AssetDatabase.LoadAssetAtPath<TextAsset>(path);
            var camera = new GameObject("Main Camera").AddComponent<Camera>();
            camera.tag = "MainCamera";
            camera.transform.position = new Vector3(3, 2, -6);
            camera.transform.LookAt(new Vector3(0, 0.9f, -1.5f));
            camera.fieldOfView = 50;
            camera.backgroundColor = new Color(0.08f, 0.13f, 0.16f);
            var light = new GameObject("Key Light").AddComponent<Light>();
            light.type = LightType.Directional;
            light.intensity = 1.2f;
            light.transform.rotation = Quaternion.Euler(45, -30, 0);
            GameObject.CreatePrimitive(PrimitiveType.Plane).name = "Ground";
            RenderSettings.ambientLight = new Color(0.6f, 0.6f, 0.6f);
            Selection.activeGameObject = player.gameObject;
            EditorSceneManager.MarkSceneDirty(EditorSceneManager.GetActiveScene());
        }
    }
}
