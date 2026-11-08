using System;
using System.Collections.Generic;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Threading.Tasks;
using UnityEditor;
using UnityEngine;

namespace AstraUnity.Editor
{
    [InitializeOnLoad]
    public static class AstraDualSelfTest
    {
        private const string Pending = "AstraDualSelfTest.Pending";
        [Serializable] private sealed class Report { public bool passed; public string error; public string[] checks; }
        static AstraDualSelfTest() { EditorApplication.playModeStateChanged += OnStateChanged; }

        public static void Run()
        {
            AstraSkeletonSetup.BuildDualScene();
            EditorApplication.delayCall += () => EditorApplication.delayCall += () => {
                SessionState.SetBool(Pending, true); EditorApplication.EnterPlaymode();
            };
        }

        private static async void OnStateChanged(PlayModeStateChange state)
        {
            if (state != PlayModeStateChange.EnteredPlayMode || !SessionState.GetBool(Pending, false)) return;
            SessionState.SetBool(Pending, false);
            var checks = new List<string>();
            var report = new Report();
            System.Diagnostics.Process sender = null;
            string root = Path.GetFullPath(Path.Combine(Application.dataPath, "../.."));
            try
            {
                var first = GameObject.Find("Camera 1 Skeleton");
                var second = GameObject.Find("Camera 2 Skeleton");
                var r1 = first.GetComponent<AstraSkeletonReceiver>();
                var r2 = second.GetComponent<AstraSkeletonReceiver>();
                var v1 = first.GetComponent<AstraSkeletonView>();
                var v2 = second.GetComponent<AstraSkeletonView>();
                if (r1.port != 7001 || r2.port != 7002 || r1.LastError != null || r2.LastError != null)
                    throw new Exception("Two receivers failed to bind independent ports: " + r1.LastError + " " + r2.LastError);
                checks.Add("Two independent receiver ports bind");
                string exe = Path.Combine(root, "integrations/astra-unity-bridge/build/bin/Release/AstraUnityBridge.exe");
                sender = System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo(exe, "--dual --simulate --frames 120") {
                    WorkingDirectory = Path.GetDirectoryName(exe), UseShellExecute = false, CreateNoWindow = true
                });
                await Task.Delay(3500);
                if (!r1.IsReceiving || !r2.IsReceiving || r1.AcceptedFrames < 20 || r2.AcceptedFrames < 20)
                    throw new Exception("Both independent streams must receive live packets");
                checks.Add("Both native simulation streams reach Unity");
                if (v1.VisibleBodies != 1 || v2.VisibleBodies != 1 || r1.LatestFrame.bodies.Length != 1 || r2.LatestFrame.bodies.Length != 1)
                    throw new Exception("Expected one skeleton per camera");
                checks.Add("Exactly two skeletons appear, one per stream");
                var hand1 = first.transform.Find("Body 1/LeftHand").position;
                var hand2 = second.transform.Find("Body 1/LeftHand").position;
                if (hand2.x - hand1.x < 1.5f) throw new Exception("Skeletons should occupy separate display positions");
                checks.Add("Skeletons display side by side even when body IDs match");
                if (Vector3.Distance(r1.LatestFrame.bodies[0].Joint(JointType.LeftHand).position,
                    r2.LatestFrame.bodies[0].Joint(JointType.LeftHand).position) < 10f)
                    throw new Exception("Simulated camera motions must be independent");
                checks.Add("Streams carry independent motions");
                r1.enabled = false;
                await Task.Delay(200);
                if (!r2.IsReceiving || v2.VisibleBodies != 1 || r1.IsReceiving)
                    throw new Exception("First receiver must not affect the second");
                checks.Add("Stopping one receiver leaves the other running");
                report.passed = true;
            }
            catch (Exception e) { report.error = e.ToString(); Debug.LogException(e); }
            finally
            {
                if (sender != null) { if (!sender.HasExited) sender.Kill(); sender.Dispose(); }
                report.checks = checks.ToArray();
                Directory.CreateDirectory(Path.Combine(root, "integrations/astra-unity-bridge/logs"));
                File.WriteAllText(Path.Combine(root, "integrations/astra-unity-bridge/logs/unity-dual-self-test.json"), JsonUtility.ToJson(report, true));
                Debug.Log("ASTRA DUAL TEST: " + (report.passed ? "PASS" : "FAIL"));
                EditorApplication.Exit(report.passed ? 0 : 1);
            }
        }
    }
}
