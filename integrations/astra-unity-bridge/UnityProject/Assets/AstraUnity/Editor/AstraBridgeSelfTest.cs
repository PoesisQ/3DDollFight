using System;
using System.Collections.Generic;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Threading.Tasks;
using UnityEditor;
using UnityEngine;

namespace AstraUnity.Editor
{
    [InitializeOnLoad]
    public static class AstraBridgeSelfTest
    {
        private const string Pending = "AstraBridgeSelfTest.Pending";
        private static readonly List<string> checks = new List<string>();
        [Serializable] private sealed class Result { public bool passed; public string[] checks; public string error; }

        static AstraBridgeSelfTest() { EditorApplication.playModeStateChanged += StateChanged; }

        public static void Run()
        {
            AstraSkeletonSetup.BuildScene();
            // Let the new project's editor indexes finish first-use initialization before Play Mode.
            EditorApplication.delayCall += () => {
                EditorApplication.delayCall += () => {
                    SessionState.SetBool(Pending, true);
                    EditorApplication.EnterPlaymode();
                };
            };
        }

        private static void Assert(bool condition, string label)
        {
            if (!condition) throw new Exception(label);
            checks.Add(label);
        }

        private static async void StateChanged(PlayModeStateChange state)
        {
            if (state != PlayModeStateChange.EnteredPlayMode || !SessionState.GetBool(Pending, false)) return;
            SessionState.SetBool(Pending, false);
            var result = new Result();
            System.Diagnostics.Process sender = null;
            var root = Path.GetFullPath(Path.Combine(Application.dataPath, "../.."));
            try
            {
                var receiver = UnityEngine.Object.FindFirstObjectByType<AstraSkeletonReceiver>();
                var view = UnityEngine.Object.FindFirstObjectByType<AstraSkeletonView>();
                receiver.enabled = false;
                using (var reserve = new UdpClient(new IPEndPoint(IPAddress.Loopback, 0)))
                    receiver.port = ((IPEndPoint)reserve.Client.LocalEndPoint).Port;
                receiver.enabled = true;
                Assert(string.IsNullOrEmpty(receiver.LastError), "UDP receiver starts");
                var exe = Path.Combine(root, "build/bin/Release/AstraUnityBridge.exe");
                sender = System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo(exe,
                    "--simulate --frames 120 --port " + receiver.port) {
                    WorkingDirectory = Path.GetDirectoryName(exe), UseShellExecute = false, CreateNoWindow = true
                });
                await Task.Delay(700);
                Assert(receiver.IsReceiving, "Native sender reaches Unity through UDP");
                Assert(receiver.LatestFrame.simulated && receiver.LatestFrame.IsValid(), "Unity parses versioned simulated skeleton frame");
                Assert(receiver.LatestFrame.bodies.Length == 1 && receiver.LatestFrame.bodies[0].joints.Length == 19,
                    "All 19 joints are received");
                var firstHand = receiver.LatestFrame.bodies[0].Joint(JointType.LeftHand).position;
                Assert(Vector3.Distance(receiver.ToLocalPosition(new Vector3(1000, 2000, 3000)), new Vector3(1,2,3)) < 0.0001f,
                    "Millimeters convert to Unity meters");
                receiver.mirrorX = true;
                Assert(receiver.ToLocalPosition(new Vector3(1000,0,0)).x == -1, "Mirror option flips X");
                receiver.mirrorX = false;
                await Task.Delay(2800);
                Assert(receiver.AcceptedFrames > 20, "Continuous stream updates across frames");
                Assert(Vector3.Distance(firstHand, receiver.LatestFrame.bodies[0].Joint(JointType.LeftHand).position) > 50,
                    "Arm motion arrives in Unity");
                Assert(view.VisibleBodies == 1, "Unity creates visible skeleton");
                var bodyRoot = view.transform.Find("Body 1");
                Assert(bodyRoot != null && bodyRoot.GetComponentsInChildren<LineRenderer>().Length == 18,
                    "Skeleton has 18 bone segments");
                int activeJoints = 0;
                foreach (Transform child in bodyRoot)
                    if (child.gameObject.activeSelf && child.GetComponent<MeshRenderer>() != null) ++activeJoints;
                Assert(activeJoints == 19, "Skeleton has 19 visible joint spheres");
                if (SystemInfo.graphicsDeviceType != UnityEngine.Rendering.GraphicsDeviceType.Null)
                {
                    var camera = Camera.main;
                    var texture = new RenderTexture(1280, 720, 24);
                    var image = new Texture2D(1280, 720, TextureFormat.RGB24, false);
                    var previous = RenderTexture.active;
                    try
                    {
                        camera.targetTexture = texture; camera.Render(); RenderTexture.active = texture;
                        image.ReadPixels(new Rect(0, 0, 1280, 720), 0, 0); image.Apply();
                        Directory.CreateDirectory(Path.Combine(root, "logs"));
                        File.WriteAllBytes(Path.Combine(root, "logs/skeleton-preview.png"), image.EncodeToPNG());
                        Assert(true, "Rendered skeleton preview captured");
                    }
                    finally
                    {
                        camera.targetTexture = null; RenderTexture.active = previous;
                        texture.Release(); UnityEngine.Object.Destroy(texture); UnityEngine.Object.Destroy(image);
                    }
                }
                var last = JsonUtility.FromJson<SkeletonFrame>(JsonUtility.ToJson(receiver.LatestFrame));
                await Task.Delay(1700);
                Assert(sender.HasExited && sender.ExitCode == 0, "Native sender exits cleanly after 120 frames");
                Assert(!receiver.IsReceiving && view.VisibleBodies == 0, "Stale stream hides the skeleton");

                using (var udp = new UdpClient())
                {
                    Action<string> send = json => { var bytes = Encoding.UTF8.GetBytes(json); udp.Send(bytes, bytes.Length, "127.0.0.1", receiver.port); };
                    last.sequence += 1000;
                    send(JsonUtility.ToJson(last)); await Task.Delay(180);
                    Assert(receiver.IsReceiving && view.VisibleBodies == 1, "Stream can recover after timeout");
                    long count = receiver.AcceptedFrames;
                    send(JsonUtility.ToJson(last)); await Task.Delay(120);
                    Assert(receiver.AcceptedFrames == count, "Duplicate frames are ignored");
                    last.sequence -= 1; send(JsonUtility.ToJson(last)); await Task.Delay(120);
                    Assert(receiver.AcceptedFrames == count, "Out-of-order frames are ignored");
                    send("not-json"); await Task.Delay(120);
                    Assert(receiver.AcceptedFrames == count, "Malformed JSON is ignored");
                    last.sequence += 2;
                    last.bodies[0].joints[4].status = 0;
                    send(JsonUtility.ToJson(last)); await Task.Delay(180);
                    Assert(!view.transform.Find("Body 1/LeftHand").gameObject.activeSelf, "Untracked joints are hidden");
                    var other = JsonUtility.FromJson<SkeletonFrame>(JsonUtility.ToJson(last)).bodies[0];
                    other.id = 2;
                    last.sequence += 1; last.bodies = new[] { other, last.bodies[0] };
                    send(JsonUtility.ToJson(last)); await Task.Delay(180);
                    Assert(receiver.LatestFrame.bodies.Length == 1 && receiver.SelectedBodyId == 1 && view.VisibleBodies == 1,
                        "Two people yield one selected skeleton, keeping the original person");
                    last.sequence += 1; last.bodies[1].status = 1;
                    send(JsonUtility.ToJson(last)); await Task.Delay(180);
                    Assert(receiver.LatestFrame.bodies.Length == 1 && receiver.SelectedBodyId == 2 && view.VisibleBodies == 1,
                        "Selection switches when the original person is lost");
                    last.sequence += 1; last.bodies[1].status = 3;
                    send(JsonUtility.ToJson(last)); await Task.Delay(180);
                    Assert(receiver.SelectedBodyId == 2 && view.VisibleBodies == 1,
                        "Newly appearing person does not replace the current person");
                    last.sequence += 1; last.bodies[0].status = 1; last.bodies[1].status = 1;
                    send(JsonUtility.ToJson(last)); await Task.Delay(180);
                    Assert(receiver.SelectedBodyId == 0 && view.VisibleBodies == 0, "Lost bodies are removed immediately");
                    last.sequence += 1; last.bodies = new SkeletonBody[0];
                    send(JsonUtility.ToJson(last)); await Task.Delay(180);
                    Assert(receiver.IsReceiving && view.VisibleBodies == 0, "Empty body frame clears the scene without losing the connection");
                }
                receiver.enabled = false; receiver.enabled = true;
                Assert(string.IsNullOrEmpty(receiver.LastError), "Receiver releases its socket and rebinds cleanly");
                result.passed = true;
            }
            catch (Exception e) { result.error = e.ToString(); Debug.LogException(e); }
            finally
            {
                if (sender != null) { if (!sender.HasExited) sender.Kill(); sender.Dispose(); }
                result.checks = checks.ToArray();
                Directory.CreateDirectory(Path.Combine(root, "logs"));
                File.WriteAllText(Path.Combine(root, "logs/unity-self-test.json"), JsonUtility.ToJson(result, true));
                Debug.Log("ASTRA BRIDGE SELF TEST: " + (result.passed ? "PASS" : "FAIL") + " (" + checks.Count + " checks)");
                EditorApplication.Exit(result.passed ? 0 : 1);
            }
        }
    }
}
