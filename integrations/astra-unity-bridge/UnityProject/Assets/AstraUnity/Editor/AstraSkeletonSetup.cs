using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

namespace AstraUnity.Editor
{
    public static class AstraSkeletonSetup
    {
        [MenuItem("Tools/Astra Skeleton/Create Demo Scene")]
        public static void CreateDemoScene()
        {
            if (!EditorSceneManager.SaveCurrentModifiedScenesIfUserWantsTo()) return;
            BuildScene();
        }

        public static void BuildScene()
        {
            EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
            var rig = new GameObject("Astra Skeleton");
            var receiver = rig.AddComponent<AstraSkeletonReceiver>();
            rig.AddComponent<AstraSkeletonView>().receiver = receiver;
            var camera = new GameObject("Main Camera").AddComponent<Camera>();
            camera.tag = "MainCamera"; camera.transform.position = new Vector3(0, 0, -3);
            camera.transform.rotation = Quaternion.identity; camera.orthographic = true; camera.orthographicSize = 1.15f;
            camera.clearFlags = CameraClearFlags.SolidColor; camera.backgroundColor = new Color(0.035f, 0.055f, 0.09f);
            camera.nearClipPlane = 0.05f; camera.farClipPlane = 30;
            Selection.activeGameObject = rig;
        }

        // Batch-mode entry point used to create the included scene without altering other projects.
        public static void CreateAndSaveDemo()
        {
            BuildScene();
            EditorSceneManager.SaveScene(EditorSceneManager.GetActiveScene(), "Assets/AstraUnity/Demo.unity");
            EditorBuildSettings.scenes = new[] { new EditorBuildSettingsScene("Assets/AstraUnity/Demo.unity", true) };
        }

        public static void OpenDemo()
        {
            EditorSceneManager.OpenScene("Assets/AstraUnity/Demo.unity");
        }

        [MenuItem("Tools/Astra Skeleton/Create Two Camera Demo Scene")]
        public static void CreateDualScene()
        {
            if (!EditorSceneManager.SaveCurrentModifiedScenesIfUserWantsTo()) return;
            BuildDualScene();
        }

        public static void BuildDualScene()
        {
            BuildScene();
            var first = GameObject.Find("Astra Skeleton");
            first.name = "Camera 1 Skeleton";
            first.transform.position = new Vector3(-1.15f, 0, 0);
            var second = new GameObject("Camera 2 Skeleton");
            second.transform.position = new Vector3(1.15f, 0, 0);
            var receiver = second.AddComponent<AstraSkeletonReceiver>();
            receiver.port = 7002;
            var view = second.AddComponent<AstraSkeletonView>();
            view.receiver = receiver; view.statusTop = 58;
            Camera.main.orthographicSize = 1.45f;
            Selection.activeGameObject = first;
        }

        public static void CreateAndSaveDualDemo()
        {
            const string path = "Assets/AstraUnity/DualCameraDemo.unity";
            if (System.IO.File.Exists(path)) throw new System.InvalidOperationException("DualCameraDemo.unity already exists; refusing to overwrite it.");
            BuildDualScene();
            if (!EditorSceneManager.SaveScene(EditorSceneManager.GetActiveScene(), path))
                throw new System.InvalidOperationException("Could not save the dual-camera scene.");
        }

        public static void OpenDualDemo()
        {
            EditorSceneManager.OpenScene("Assets/AstraUnity/DualCameraDemo.unity");
        }
    }
}
