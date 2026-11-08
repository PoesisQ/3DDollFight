using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

namespace AstraUnity.Editor
{
    public static class AstraSkeletonSetup
    {
        public const string ScenePath = "Assets/AstraUnity/DualCameraDemo.unity";

        [MenuItem("DollFight/Astra/Open Dual Skeleton Demo")]
        public static void OpenDualDemo()
        {
            if (!EditorSceneManager.SaveCurrentModifiedScenesIfUserWantsTo()) return;
            EditorSceneManager.OpenScene(ScenePath);
        }

        [MenuItem("DollFight/Astra/Create Dual Skeleton Scene")]
        public static void CreateDualScene()
        {
            if (!EditorSceneManager.SaveCurrentModifiedScenesIfUserWantsTo()) return;
            BuildDualScene();
        }

        public static void BuildDualScene()
        {
            EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
            for (int i = 0; i < 2; ++i)
            {
                var rig = new GameObject("Camera " + (i + 1) + " Skeleton");
                rig.transform.position = new Vector3(i == 0 ? -1.15f : 1.15f, 0, 0);
                var receiver = rig.AddComponent<AstraSkeletonReceiver>();
                receiver.port = 7001 + i;
                var view = rig.AddComponent<AstraSkeletonView>();
                view.receiver = receiver;
                view.statusTop = 12 + 46 * i;
            }
            var camera = new GameObject("Main Camera").AddComponent<Camera>();
            camera.tag = "MainCamera";
            camera.transform.position = new Vector3(0, 0, -3);
            camera.orthographic = true; camera.orthographicSize = 1.45f;
            camera.clearFlags = CameraClearFlags.SolidColor;
            camera.backgroundColor = new Color(0.035f, 0.055f, 0.09f);
            camera.nearClipPlane = 0.05f; camera.farClipPlane = 30;
            EditorSceneManager.MarkSceneDirty(EditorSceneManager.GetActiveScene());
        }

        // Noninteractive scene check: does not replace or save any scene assets.
        public static void VerifyScene()
        {
            var scene = EditorSceneManager.OpenScene(ScenePath);
            var receivers = Object.FindObjectsByType<AstraSkeletonReceiver>(FindObjectsSortMode.None);
            if (!scene.IsValid() || receivers.Length != 2 || receivers[0].port == receivers[1].port)
                throw new System.InvalidOperationException("Dual skeleton scene must have two separate receivers.");
            Debug.Log("ASTRA_GAME_SCENE_OK");
        }
    }
}
