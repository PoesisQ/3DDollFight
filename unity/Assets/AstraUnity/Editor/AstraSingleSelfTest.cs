using System;
using System.IO;
using System.Threading.Tasks;
using DollFight;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

namespace AstraUnity.Editor
{
    [InitializeOnLoad]
    public static class AstraSingleSelfTest
    {
        const string Pending = "AstraSingleSelfTest.Pending";
        static AstraSingleSelfTest() { EditorApplication.playModeStateChanged += Changed; }
        public static void Run()
        {
            EditorSceneManager.OpenScene(AstraLiveScene.ScenePath);
            EditorApplication.delayCall += () => { SessionState.SetBool(Pending, true); EditorApplication.EnterPlaymode(); };
        }
        static async void Changed(PlayModeStateChange state)
        {
            if (state != PlayModeStateChange.EnteredPlayMode || !SessionState.GetBool(Pending, false)) return;
            SessionState.SetBool(Pending, false);
            System.Diagnostics.Process sender = null;
            try
            {
                var sample = new SkeletonBody { joints = new[] {
                    new SkeletonJoint { type = (int)JointType.MidSpine, status = 2, position = new Vector3(0, 200, 1400) },
                    new SkeletonJoint { type = (int)JointType.BaseSpine, status = 2, position = new Vector3(200, 0, 1800) }
                }};
                Vector3 midpoint;
                if (!sample.TryInterpolate(JointType.MidSpine, JointType.BaseSpine, out midpoint) ||
                    Vector3.Distance(midpoint, new Vector3(100, 100, 1600)) > 0.001f)
                    throw new Exception("Derived body point must retain all 3 dimensions");
                sample.joints[0].status = 0;
                if (sample.TryInterpolate(JointType.MidSpine, JointType.BaseSpine, out midpoint))
                    throw new Exception("Cannot infer a point from an untracked joint");
                var live = UnityEngine.Object.FindFirstObjectByType<AstraLivePlayer>();
                if (live == null || live.receiver == null) throw new Exception("Single-camera receiver missing");
                live.autoStartRecognition = false;
                DollFightDemo game = null;
                for (int i = 0; i < 150; i++)
                {
                    game = UnityEngine.Object.FindFirstObjectByType<DollFightDemo>();
                    if (game != null && game.Ready) break;
                    await Task.Delay(200);
                }
                if (game == null || !game.Ready) throw new Exception("Game did not finish loading its actual avatars: " + (game != null ? game.status : "missing"));
                game.SelectionScreen.Hide();
                string root = Path.GetFullPath(Path.Combine(Application.dataPath, "../.."));
                string exe = Path.Combine(root, "integrations/astra-unity-bridge/build/bin/Release/AstraUnityBridge.exe");
                sender = System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo(exe, "--simulate --frames 180") {
                    WorkingDirectory = Path.GetDirectoryName(exe), UseShellExecute = false, CreateNoWindow = true
                });
                await Task.Delay(650);
                if (!live.receiver.IsReceiving || live.receiver.LatestFrame.bodies.Length != 1)
                    throw new Exception("No simulated P1 body");
                if (!live.Calibrate(live.receiver.LatestFrame.bodies[0])) throw new Exception("Calibration failed");
                await Task.Delay(400);
                Quaternion initial = game.Actors[0].Bones[5].rotation;
                await Task.Delay(2700);
                float angle = Quaternion.Angle(initial, game.Actors[0].Bones[5].rotation);
                if (angle < 5) throw new Exception("P1 arm did not follow simulated motion; angle " + angle);
                if (game.playing) throw new Exception("Prerecorded combat must remain paused");
                int receiverId = live.receiver.GetInstanceID();
                UnityEngine.SceneManagement.SceneManager.LoadScene("DollFight");
                await Task.Delay(800);
                var surviving = UnityEngine.Object.FindFirstObjectByType<AstraLivePlayer>();
                if (surviving == null || surviving.receiver.GetInstanceID() != receiverId)
                    throw new Exception("Camera receiver did not survive selecting a game scene");
                Debug.Log("ASTRA_SINGLE_GAME_TEST_PASS angle=" + angle);
                EditorApplication.Exit(0);
            }
            catch (Exception e) { Debug.LogException(e); EditorApplication.Exit(1); }
            finally { if (sender != null) { if (!sender.HasExited) sender.Kill(); sender.Dispose(); } }
        }
    }
}
