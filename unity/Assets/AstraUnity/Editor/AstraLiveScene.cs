using System.IO;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

namespace AstraUnity.Editor
{
    public static class AstraLiveScene
    {
        public const string ScenePath = "Assets/AstraUnity/SingleCameraGame.unity";
        public static void Create()
        {
            if (File.Exists(ScenePath)) throw new System.InvalidOperationException("SingleCameraGame already exists; will not overwrite it.");
            var scene = EditorSceneManager.OpenScene("Assets/Scenes/DollFight.unity");
            var obj = new GameObject("Astra Live P1");
            obj.AddComponent<AstraSkeletonReceiver>();
            obj.AddComponent<AstraLivePlayer>();
            if (!EditorSceneManager.SaveScene(scene, ScenePath)) throw new System.InvalidOperationException("Scene save failed");
        }
        [MenuItem("DollFight/Astra/Open Single Camera Game")]
        public static void Open()
        {
            if (EditorSceneManager.SaveCurrentModifiedScenesIfUserWantsTo()) EditorSceneManager.OpenScene(ScenePath);
        }
    }
}
