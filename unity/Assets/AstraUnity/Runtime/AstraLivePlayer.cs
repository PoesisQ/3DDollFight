using System;
using System.IO;
using System.Diagnostics;
using System.Collections.Generic;
using DollFight;
using UnityEngine;

namespace AstraUnity
{
    // Experimental position-based P1 retargeting. Offline combat remains paused.
    [DefaultExecutionOrder(12500)]
    public sealed class AstraLivePlayer : MonoBehaviour
    {
        public AstraSkeletonReceiver receiver;
        public float smoothing = 12f;
        public string status = "Waiting for game and camera";
        public bool Calibrated { get; private set; }
        public int CalibratedBodyId { get; private set; }
        private string calibratedSession;
        private DollFightDemo game;
        private HumanoidReplay actor;
        private readonly Quaternion[] bindRotations = new Quaternion[19];
        private readonly Quaternion[] liveRotations = new Quaternion[19];
        private readonly Vector3[] baseline = new Vector3[19];
        private Vector3 baseHip;
        private Vector3 sensorHip;
        private Vector3 liveHip;
        private Vector3 initialHip;
        private Vector3 sourceRight, sourceDepth, modelRight, modelDepth;
        private Quaternion previousFacing = Quaternion.identity;
        private static readonly int[,] segments = {
            {0,9,8},{1,8,1},{2,1,18},{3,18,0},
            {5,2,3},{6,3,16},{8,5,6},{9,6,17},
            {11,10,11},{15,13,14}
        };
        private readonly bool[] valid = new bool[19];
        private System.Diagnostics.Process sender;
        private readonly object messageLock = new object();
        private string senderMessage = "未启动";
        private string senderError;
        private const float CalibrationInterval = 5f;
        private float nextCalibrationAt = -1f;
        private string calibrationMessage;
        private float calibrationMessageUntil;
        private Font uiFont;
        private Camera playerWorldCamera, playerBodyCamera;

        void SetSenderMessage(string message)
        {
            if (string.IsNullOrWhiteSpace(message)) return;
            lock (messageLock) senderMessage = message.Length > 160 ? message.Substring(0, 160) : message;
        }

        void SetSenderError(string message)
        {
            if (string.IsNullOrWhiteSpace(message)) return;
            lock (messageLock) senderError = message.Length > 160 ? message.Substring(0, 160) : message;
        }

        public void StartSender(bool simulated)
        {
            if (sender != null && !sender.HasExited) { SetSenderMessage("发送程序已运行，请先停止后切换模式。"); return; }
            if (sender != null) { sender.Dispose(); sender = null; }
            lock (messageLock) senderError = null;
            var root = Path.GetFullPath(Path.Combine(Application.dataPath, "../.."));
            var exe = Path.Combine(root, "integrations/astra-unity-bridge/build/bin/Release/AstraUnityBridge.exe");
            if (!File.Exists(exe)) { SetSenderMessage("找不到发送程序，请先运行 Build-Bridge.cmd。"); return; }
            string args = simulated ? "--simulate --warmup 6" : "";
            var license = Environment.GetEnvironmentVariable("ASTRA_BODY_LICENSE");
            var lab = Environment.GetEnvironmentVariable("ASTRA_LAB_ENV");
            if (!simulated && string.IsNullOrEmpty(license) && !string.IsNullOrEmpty(lab))
            {
                var candidate = Path.Combine(lab, "astra-body-license.txt");
                if (File.Exists(candidate)) license = candidate;
            }
            if (!simulated && !string.IsNullOrEmpty(license))
            {
                if (!File.Exists(license)) { SetSenderMessage("授权文件不存在，请检查 ASTRA_BODY_LICENSE。"); return; }
                args += " --license \"" + license + "\"";
            }
            try
            {
                sender = new System.Diagnostics.Process();
                sender.StartInfo = new ProcessStartInfo(exe, args) {
                    WorkingDirectory = Path.GetDirectoryName(exe), UseShellExecute = false,
                    CreateNoWindow = true, RedirectStandardOutput = true, RedirectStandardError = true
                };
                sender.OutputDataReceived += (s, e) => SetSenderMessage(e.Data);
                sender.ErrorDataReceived += (s, e) => SetSenderError(e.Data);
                sender.Start(); sender.BeginOutputReadLine(); sender.BeginErrorReadLine();
                SetSenderMessage(simulated ? "模拟数据启动中…" : "摄像头启动中…");
            }
            catch (Exception e) { SetSenderMessage("启动失败：" + e.Message); if (sender != null) sender.Dispose(); sender = null; }
        }

        public void StopSender()
        {
            if (sender == null) return;
            try { if (!sender.HasExited) sender.Kill(); }
            catch (InvalidOperationException) { }
            finally { sender.Dispose(); sender = null; lock (messageLock) senderError = null; SetSenderMessage("已停止本程序启动的数据源"); }
        }

        void Awake()
        {
            if (receiver == null) receiver = GetComponent<AstraSkeletonReceiver>();
            game = FindFirstObjectByType<DollFightDemo>();
            if (receiver == null || game == null) { status = "Missing receiver or DollFightDemo"; enabled = false; return; }
            DontDestroyOnLoad(gameObject);
        }

        void Update()
        {
            if (game == null) { game = FindFirstObjectByType<DollFightDemo>(); actor = null; Calibrated = false; }
            if (game == null || !game.Ready || game.Actors == null || game.Actors[0] == null) return;
            if (actor != game.Actors[0])
            {
                actor = game.Actors[0]; Calibrated = false;
                initialHip = actor.Bones[0].position;
                playerWorldCamera = playerBodyCamera = null;
            }
            game.playing = false; // Do not present prerecorded fighting events as live results.
            if (game.SelectionOpen) { status = "Choose characters and arena, then press C in T-pose"; return; }
            if (!receiver.IsReceiving || receiver.LatestFrame.bodies.Length == 0)
            {
                Calibrated = false; nextCalibrationAt = -1f; status = "Waiting for tracked person"; return;
            }
            var body = receiver.LatestFrame.bodies[0];
            if (Calibrated && (body.id != CalibratedBodyId || calibratedSession != receiver.LatestFrame.session))
            { Calibrated = false; nextCalibrationAt = -1f; }
            if (nextCalibrationAt < 0) nextCalibrationAt = Time.unscaledTime + CalibrationInterval;
            if (Time.unscaledTime >= nextCalibrationAt)
            {
                nextCalibrationAt = Time.unscaledTime + CalibrationInterval;
                string reason = CalibrationIssue(body);
                if (reason != null || !IsCalibrationPose(body) || !Calibrate(body))
                {
                    calibrationMessage = "自动校准失败：" + (reason ?? "请面向摄像头双臂平举");
                    calibrationMessageUntil = nextCalibrationAt;
                }
                else { calibrationMessage = null; calibrationMessageUntil = 0; }
            }
            if (!Calibrated) status = "Waiting for automatic T-pose calibration";
        }

        bool IsCalibrationPose(SkeletonBody body)
        {
            var left = body.Joint(JointType.LeftShoulder); var right = body.Joint(JointType.RightShoulder);
            var leftWrist = body.Joint(JointType.LeftWrist); var rightWrist = body.Joint(JointType.RightWrist);
            if (left == null || right == null || leftWrist == null || rightWrist == null ||
                left.status == 0 || right.status == 0 || leftWrist.status == 0 || rightWrist.status == 0) return false;
            Vector3 l = receiver.ToLocalPosition(left.position), r = receiver.ToLocalPosition(right.position);
            Vector3 lw = receiver.ToLocalPosition(leftWrist.position), rw = receiver.ToLocalPosition(rightWrist.position);
            float shoulderWidth = Vector3.Distance(l, r);
            if (shoulderWidth < 0.15f) return false;
            return Mathf.Abs(lw.y - l.y) < shoulderWidth * 0.8f && Mathf.Abs(rw.y - r.y) < shoulderWidth * 0.8f &&
                Mathf.Abs(lw.x - l.x) > shoulderWidth * 0.4f && Mathf.Abs(rw.x - r.x) > shoulderWidth * 0.4f &&
                (lw.x - l.x) * (rw.x - r.x) < 0;
        }

        public bool Calibrate(SkeletonBody body)
        {
            if (actor == null || body == null || !body.IsTracked) return false;
            for (int i = 0; i < segments.GetLength(0); i++)
            {
                Vector3 direction;
                if (!Direction(body, segments[i,1], segments[i,2], out direction))
                { status = "Calibration needs all main joints tracked"; return false; }
            }
            var hip = body.Joint(JointType.BaseSpine);
            if (hip == null || hip.status < 1) return false;
            // Preserve the game position when restoring the imported T-pose.
            Vector3 anchor = Calibrated ? liveHip : initialHip;
            actor.RestoreBindPose();
            var bones = actor.Bones;
            bones[0].position = anchor;
            Vector3 shoulders = bones[8].position - bones[5].position;
            shoulders.y = 0;
            Vector3 opponentDirection;
            if (shoulders.sqrMagnitude > 0.0001f && DirectionToOpponent(anchor, out opponentDirection))
            {
                Vector3 forward = Vector3.Cross(shoulders.normalized, Vector3.up);
                bones[0].rotation = FaceDirection(forward, opponentDirection) * bones[0].rotation;
            }
            for (int i = 0; i < 19; i++) { bindRotations[i] = bones[i].rotation; liveRotations[i] = bones[i].rotation; valid[i] = false; }
            previousFacing = Quaternion.identity;
            baseHip = anchor;
            liveHip = baseHip;
            sensorHip = receiver.ToWorldPosition(hip.position);
            // Match the shoulder axes and reverse depth: the person faces the
            // sensor while the avatar faces the opponent.
            sourceRight = receiver.ToWorldPosition(body.Joint(JointType.RightShoulder).position) -
                          receiver.ToWorldPosition(body.Joint(JointType.LeftShoulder).position);
            modelRight = bones[8].position - bones[5].position;
            sourceRight.y = 0; modelRight.y = 0;
            if (sourceRight.sqrMagnitude < 0.0001f || modelRight.sqrMagnitude < 0.0001f)
            { status = "Calibration needs separated shoulders"; return false; }
            sourceRight.Normalize(); modelRight.Normalize();
            sourceDepth = Vector3.Cross(sourceRight, Vector3.up);
            modelDepth = Vector3.Cross(modelRight, Vector3.up);
            for (int i = 0; i < segments.GetLength(0); i++)
            {
                int bone = segments[i,0]; Vector3 v;
                valid[bone] = Direction(body, segments[i,1], segments[i,2], out v);
                baseline[bone] = v;
            }
            CalibratedBodyId = body.id; calibratedSession = receiver.LatestFrame.session;
            Calibrated = true; status = "Live P1; replay combat paused";
            return true;
        }

        bool Direction(SkeletonBody body, int a, int b, out Vector3 vector)
        {
            vector = Vector3.zero;
            var first = body.Joint((JointType)a); var second = body.Joint((JointType)b);
            if (first == null || second == null || first.status < 1 || second.status < 1) return false;
            vector = receiver.ToWorldPosition(second.position) - receiver.ToWorldPosition(first.position);
            if (sourceRight.sqrMagnitude > 0.5f) vector = MapSensorOffset(vector);
            if (vector.sqrMagnitude < 0.0001f) return false;
            vector.Normalize(); return true;
        }

        Vector3 MapSensorOffset(Vector3 offset)
        {
            return modelRight * Vector3.Dot(offset, sourceRight) +
                   Vector3.up * offset.y - modelDepth * Vector3.Dot(offset, sourceDepth);
        }

        bool DirectionToOpponent(Vector3 position, out Vector3 direction)
        {
            direction = Vector3.zero;
            if (game == null || game.Actors == null || game.Actors.Length < 2 ||
                game.Actors[1] == null || game.Actors[1].Bones == null || game.Actors[1].Bones[0] == null)
                return false;
            direction = game.Actors[1].Bones[0].position - position;
            direction.y = 0;
            if (direction.sqrMagnitude < 0.0001f) return false;
            direction.Normalize();
            return true;
        }

        static Quaternion FaceDirection(Vector3 from, Vector3 to)
        {
            return Quaternion.LookRotation(to, Vector3.up) *
                   Quaternion.Inverse(Quaternion.LookRotation(from, Vector3.up));
        }

        static readonly string[] jointNames = { "头", "肩部中点", "左肩", "左肘", "左手", "右肩", "右肘", "右手", "脊柱中部", "髋部中心", "左髋", "左膝", "左脚", "右髋", "右膝", "右脚", "左腕", "右腕", "颈" };
        static readonly int[,] previewBones = {
            {0,18},{18,1},{1,8},{8,9},{1,2},{2,3},{3,16},{16,4},
            {1,5},{5,6},{6,17},{17,7},{9,10},{10,11},{9,13},{13,14}
        };

        string CalibrationIssue(SkeletonBody body)
        {
            if (body == null || !body.IsTracked) return "没有识别到人体";
            var missing = new List<string>();
            var checkedJoint = new bool[19];
            for (int i = 0; i < segments.GetLength(0); i++)
                for (int n = 1; n <= 2; n++)
                {
                    int id = segments[i,n];
                    if (checkedJoint[id]) continue;
                    checkedJoint[id] = true;
                    var joint = body.Joint((JointType)id);
                    if (joint == null || joint.status == 0) missing.Add(jointNames[id]);
                }
            if (missing.Count > 0) return "未追踪：" + string.Join("、", missing.ToArray());
            for (int i = 0; i < segments.GetLength(0); i++)
            {
                Vector3 v;
                if (!Direction(body, segments[i,1], segments[i,2], out v))
                    return jointNames[segments[i,1]] + "与" + jointNames[segments[i,2]] + "位置过近";
            }
            return null;
        }

        void DrawPreview(Rect area, SkeletonBody body)
        {
            GUI.Box(area, "实时骨架正面投影（非摄像头画面）");
            if (body == null) { GUI.Label(new Rect(area.x + 12, area.y + 35, area.width - 24, 40), "等待识别人体，请全身入镜"); return; }
            var points = new Vector2[19]; var visible = new bool[19];
            float minX = float.PositiveInfinity, maxX = float.NegativeInfinity;
            float minY = float.PositiveInfinity, maxY = float.NegativeInfinity;
            int tracked = 0, low = 0;
            for (int i = 0; i < 19; i++)
            {
                if (i == (int)JointType.LeftFoot || i == (int)JointType.RightFoot) continue;
                var joint = body.Joint((JointType)i);
                if (joint == null || joint.status == 0) continue;
                var p = receiver.ToLocalPosition(joint.position);
                points[i] = new Vector2(p.x, p.y); visible[i] = true;
                minX = Mathf.Min(minX,p.x); maxX = Mathf.Max(maxX,p.x);
                minY = Mathf.Min(minY,p.y); maxY = Mathf.Max(maxY,p.y);
                if (joint.status == 2) tracked++; else low++;
            }
            if (tracked + low == 0) { GUI.Label(new Rect(area.x + 12, area.y + 35, area.width - 24, 40), "人体已识别，但没有有效关节点"); return; }
            float drawWidth = area.width - 36, drawHeight = area.height - 68;
            float scale = Mathf.Min(drawWidth / Mathf.Max(maxX-minX, 0.25f), drawHeight / Mathf.Max(maxY-minY, 0.25f));
            var center = new Vector2((minX+maxX)*0.5f,(minY+maxY)*0.5f);
            var origin = new Vector2(area.center.x, area.y + 30 + drawHeight * 0.5f);
            for (int i = 0; i < 19; i++) if (visible[i]) points[i] = origin + new Vector2((points[i].x-center.x)*scale, -(points[i].y-center.y)*scale);
            var oldColor = GUI.color;
            for (int i = 0; i < previewBones.GetLength(0); i++)
            {
                int a = previewBones[i,0], b = previewBones[i,1];
                if (!visible[a] || !visible[b]) continue;
                var d = points[b] - points[a]; var matrix = GUI.matrix;
                GUIUtility.RotateAroundPivot(Mathf.Atan2(d.y,d.x)*Mathf.Rad2Deg, points[a]);
                GUI.color = new Color(1f, 0.72f, 0.2f);
                GUI.DrawTexture(new Rect(points[a].x, points[a].y-1, d.magnitude, 2), Texture2D.whiteTexture);
                GUI.matrix = matrix;
            }
            for (int i = 0; i < 19; i++) if (visible[i])
            {
                GUI.color = body.Joint((JointType)i).status == 2 ? Color.cyan : Color.yellow;
                GUI.DrawTexture(new Rect(points[i].x-4, points[i].y-4, 8, 8), Texture2D.whiteTexture);
            }
            GUI.color = oldColor;
            GUI.Label(new Rect(area.x+10, area.yMax-28, area.width-20, 22), "正常 " + tracked + "  低置信度 " + low + "  未追踪 " + (17-tracked-low));
        }

        void LateUpdate()
        {
            if (!Calibrated || !receiver.IsReceiving || game.SelectionOpen || receiver.LatestFrame.bodies.Length == 0) return;
            var body = receiver.LatestFrame.bodies[0];
            if (body.id != CalibratedBodyId || receiver.LatestFrame.session != calibratedSession) return;
            var bones = actor.Bones;
            float t = 1f - Mathf.Exp(-Mathf.Max(0.01f, smoothing) * Time.deltaTime);
            var hip = body.Joint(JointType.BaseSpine);
            if (hip != null && hip.status > 0)
            {
                liveHip = Vector3.Lerp(liveHip, baseHip + MapSensorOffset(receiver.ToWorldPosition(hip.position) - sensorHip), t);
                bones[0].position = liveHip;
            }
            Vector3 opponentDirection;
            Quaternion facing = DirectionToOpponent(liveHip, out opponentDirection)
                ? FaceDirection(modelDepth, opponentDirection) : previousFacing;
            Quaternion facingChange = facing * Quaternion.Inverse(previousFacing);
            for (int i = 0; i < liveRotations.Length; i++) liveRotations[i] = facingChange * liveRotations[i];
            previousFacing = facing;
            // Reorient the entire model, including bones that are not tracked.
            bones[0].rotation = facing * bindRotations[0];
            for (int i = 0; i < segments.GetLength(0); i++)
            {
                int bone = segments[i,0]; Vector3 current;
                if (!valid[bone] || !Direction(body, segments[i,1], segments[i,2], out current)) continue;
                Quaternion desired = facing * Quaternion.FromToRotation(baseline[bone], current) * bindRotations[bone];
                liveRotations[bone] = Quaternion.Slerp(liveRotations[bone], desired, t);
                bones[bone].rotation = liveRotations[bone];
            }
            // The sensor foot joints are intentionally unused. Override the
            // replay pose so each model shin points straight down from its knee.
            PointShinDown(bones[12], bones[13]);
            PointShinDown(bones[16], bones[17]);
            UpdatePlayerView(body);
        }

        static void PointShinDown(Transform knee, Transform ankle)
        {
            if (knee == null || ankle == null || !ankle.IsChildOf(knee)) return;
            Vector3 direction = ankle.position - knee.position;
            if (direction.sqrMagnitude < 0.000001f) return;
            knee.rotation = Quaternion.FromToRotation(direction, Vector3.down) * knee.rotation;
        }

        void UpdatePlayerView(SkeletonBody body)
        {
            if (playerWorldCamera == null)
            {
                var obj = GameObject.Find("Player 1 opponent");
                if (obj != null) playerWorldCamera = obj.GetComponent<Camera>();
            }
            if (playerBodyCamera == null)
            {
                var obj = GameObject.Find("Player 1 body");
                if (obj != null) playerBodyCamera = obj.GetComponent<Camera>();
            }
            if (playerWorldCamera == null || playerBodyCamera == null) return;
            // The game sets its normal view in Update. Apply the head's tracked
            // tilt afterwards and keep both layered cameras at the same eye.
            Vector3 current;
            Quaternion tilt = Direction(body, (int)JointType.Neck, (int)JointType.Head, out current)
                ? Quaternion.FromToRotation(baseline[3], current) : Quaternion.identity;
            Quaternion rotation = tilt * playerWorldCamera.transform.rotation;
            Vector3 eye = actor.Bones[4].position + Vector3.up * 0.10f + rotation * Vector3.forward * 0.05f;
            playerWorldCamera.transform.SetPositionAndRotation(eye, rotation);
            playerBodyCamera.transform.SetPositionAndRotation(eye, rotation);
        }

        void OnGUI()
        {
            if (uiFont == null) uiFont = Font.CreateDynamicFontFromOSFont("Microsoft YaHei", 16);
            Font oldFont = GUI.skin.font;
            bool oldWrap = GUI.skin.label.wordWrap;
            if (uiFont != null) GUI.skin.font = uiFont;
            GUI.skin.label.wordWrap = true;
            float width = Mathf.Min(590, Screen.width - 24);
            GUI.Box(new Rect(12, 12, width, 252), "单摄像头 P1 控制 / 状态检查");
            string source;
            lock (messageLock) source = senderError ?? senderMessage;
            bool active = sender != null && !sender.HasExited;
            if (!active && sender != null && !source.StartsWith("ERROR", StringComparison.OrdinalIgnoreCase)) source = "发送程序已退出，请检查摄像头或授权。";
            GUI.Label(new Rect(25, 40, width - 24, 25), "数据源：" + source);
            string connection = !string.IsNullOrEmpty(receiver.LastError) ? receiver.LastError :
                !receiver.IsReceiving ? "未收到数据：启动摄像头或模拟数据。" :
                receiver.LatestFrame.simulated ? "已收到模拟数据" : "已收到摄像头数据";
            GUI.Label(new Rect(25, 65, width - 24, 25), "连接：" + connection);
            string bodyState = !receiver.IsReceiving ? "等待数据" : receiver.LatestFrame.bodies.Length == 0 ?
                "未识别到人：请全身入镜、面向摄像头。" : "已识别 1 人，编号 " + receiver.SelectedBodyId;
            GUI.Label(new Rect(25, 90, width - 24, 25), "人体：" + bodyState);
            string pose = game == null || !game.Ready ? "等待游戏人物加载" : game.SelectionOpen ?
                "请先完成选角和场地选择" : Time.unscaledTime < calibrationMessageUntil ? calibrationMessage :
                Calibrated ? "已校准，控制 P1（战斗回放暂停）" : "双臂平举，等待自动校准";
            GUI.Label(new Rect(25, 115, width - 24, 25), "控制：" + pose);
            if (GUI.Button(new Rect(25, 150, 120, 35), "启动摄像头")) StartSender(false);
            if (GUI.Button(new Rect(155, 150, 120, 35), "启动模拟")) StartSender(true);
            if (GUI.Button(new Rect(285, 150, 120, 35), "停止数据源")) StopSender();
            string countdown = nextCalibrationAt < 0 ? "等待人体" : "下次校准 " + Mathf.CeilToInt(Mathf.Max(0, nextCalibrationAt - Time.unscaledTime)) + " 秒";
            GUI.Label(new Rect(415, 155, 155, 30), countdown);
            GUI.Label(new Rect(25, 195, width - 24, 45), "操作：选角色和场地 → 启动摄像头 → 双臂平举并等待自动校准。\n每 5 秒尝试一次；姿势或关节不满足时保留上次校准。");
            var body = receiver.IsReceiving && receiver.LatestFrame.bodies.Length > 0 ? receiver.LatestFrame.bodies[0] : null;
            float previewHeight = Mathf.Clamp(Screen.height - 280, 150, 340);
            DrawPreview(new Rect(12, 270, Mathf.Min(width, 330), previewHeight), body);
            if (body != null && !Calibrated)
            {
                var issue = CalibrationIssue(body);
                GUI.Label(new Rect(355, 280, Mathf.Max(120, width - 345), 90), issue == null ? "关节点满足最低校准条件" : "校准检查：\n" + issue);
            }
            GUI.skin.font = oldFont;
            GUI.skin.label.wordWrap = oldWrap;
        }

        void OnDestroy() { StopSender(); if (uiFont != null) Destroy(uiFont); }
    }
}
