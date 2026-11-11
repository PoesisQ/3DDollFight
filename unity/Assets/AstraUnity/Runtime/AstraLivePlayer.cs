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
        // Selecting a character reloads the scene by name. This object survives
        // that reload, so without the guard each selection would leave a second
        // panel drawing on top of the first and a second UDP receiver fighting
        // over port 7001 — the loser reports "Cannot listen for Astra data" and
        // the two retargeters overwrite each other's pose.
        private static AstraLivePlayer live;

        public AstraSkeletonReceiver receiver;
        public AstraHandReceiver handReceiver;
        public float smoothing = 12f;
        [Tooltip("Flip if the tracked palm comes out mirrored (back of hand where the palm should be).")]
        public bool flipPalmNormal;
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
        /// <summary>
        /// Sensor frame to model frame, fixed at calibration.
        ///
        /// Every body bone is posed from a direction that went through
        /// <see cref="MapSensorOffset"/>, so all of them already live in the
        /// model's own frame. The hand basis arrives in the sensor's frame and
        /// used to be handed to the wrist unchanged: the palm then keeps the
        /// camera's idea of "forward" while the body is turned to the opponent,
        /// which is a yaw of about 90 degrees in a side-on match - the avatar
        /// holds its hand flat to the screen instead of along its own arm.
        /// </summary>
        private Quaternion sensorToModel = Quaternion.identity;
        /// <summary>Yaw applied to the whole model so it faces the opponent.</summary>
        private Quaternion liveFacing = Quaternion.identity;
        private static readonly int[,] segments = {
            {0,9,8},{1,8,1},{2,1,18},{3,18,0},
            {5,2,3},{6,3,16},{8,5,6},{9,6,17},
            {11,10,11},{15,13,14}
        };
        // Torso and arms must be solvable before calibrating. The two leg rows
        // above are optional: a desk, a chair or a tight frame usually hides the
        // knees, and a missing knee used to fail calibration outright, which
        // also stopped the hands and the wrist roll from ever being applied.
        private const int RequiredSegmentCount = 8;
        // MediaPipe hand chains: wrist, MCP, PIP, DIP, TIP.
        private static readonly int[][] handChains = {
            new[] { 0, 1, 2, 3, 4 }, new[] { 0, 5, 6, 7, 8 }, new[] { 0, 9, 10, 11, 12 },
            new[] { 0, 13, 14, 15, 16 }, new[] { 0, 17, 18, 19, 20 }
        };
        private readonly bool[] valid = new bool[19];
        private float[] handCurls;
        private Vector3[] handPoints;
        private System.Diagnostics.Process sender;
        private readonly object messageLock = new object();
        private string senderMessage = "未启动";
        private string senderError;
        private const float CalibrationInterval = 5f;
        private float nextCalibrationAt = -1f;
        // A body that vanishes for a frame or two is a detection gap, not a
        // person leaving. Throwing the calibration away for it meant every such
        // gap needed another T-pose to recover from.
        private const float BodyGrace = 2f;
        private float lastBodySeenAt = -100f;
        private bool handsDriving;
        private float lastHandApplyAt = -100f;
        // Per hand, not per pair: one hand leaving the packet says nothing about
        // the other, and the pair-wide timestamp this used to check made a single
        // lost hand relax while its partner carried on being tracked.
        private float lastLeftHandAt = -100f;
        private float lastRightHandAt = -100f;
        private const float HandGrace = 0.5f;
        private float nextGameLookupAt;
        private float nextStatusWriteAt;
        private string calibrationMessage;
        private float calibrationMessageUntil;
        private string legNote;
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
            // A duplicate only makes sense to drop when the survivor is still
            // alive. A disabled or destroyed survivor must not block the new one,
            // otherwise a failed reload leaves no panel at all.
            if (live != null && live != this && live.isActiveAndEnabled)
            { enabled = false; Destroy(gameObject); return; }
            live = this;
            if (receiver == null) receiver = GetComponent<AstraSkeletonReceiver>();
            if (handReceiver == null) handReceiver = GetComponent<AstraHandReceiver>();
            if (handReceiver == null) handReceiver = gameObject.AddComponent<AstraHandReceiver>();
            game = FindFirstObjectByType<DollFightDemo>();
            DontDestroyOnLoad(gameObject);
            if (receiver == null) { status = "缺少 AstraSkeletonReceiver 组件"; return; }
            if (game == null) status = "等待 DollFightDemo 加载";
        }

        void Update()
        {
            WriteStatus();
            if (game == null)
            {
                // Selecting a character loads another scene, so the demo we were
                // pointing at is gone. Retry instead of giving up (giving up used
                // to disable this component, which also hid the whole panel).
                if (Time.unscaledTime >= nextGameLookupAt)
                {
                    nextGameLookupAt = Time.unscaledTime + 0.5f;
                    game = FindFirstObjectByType<DollFightDemo>();
                    actor = null;
                    Calibrated = false;
                }
                if (game == null) return;
            }
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
                // One frame without a body used to erase the calibration, and
                // getting it back needed a fresh T-pose. The sensor drops the
                // body for a frame or two whenever the person leans out of the
                // pattern or a limb crosses the torso, so a session could
                // calibrate and then never work again. Hold the calibration for
                // a moment and leave the pose where it is.
                if (Calibrated && Time.unscaledTime - lastBodySeenAt < BodyGrace)
                {
                    status = "人体暂时丢失，保持校准";
                    return;
                }
                Calibrated = false; nextCalibrationAt = -1f; status = "Waiting for tracked person"; return;
            }
            lastBodySeenAt = Time.unscaledTime;
            var body = receiver.LatestFrame.bodies[0];
            if (Calibrated && (body.id != CalibratedBodyId || calibratedSession != receiver.LatestFrame.session))
            { Calibrated = false; nextCalibrationAt = -1f; }
            if (nextCalibrationAt < 0) nextCalibrationAt = Time.unscaledTime + CalibrationInterval;
            if (Time.unscaledTime >= nextCalibrationAt)
            {
                nextCalibrationAt = Time.unscaledTime + CalibrationInterval;
                // Only re-run the check when it can change the answer: while
                // uncalibrated, or when the person is actually standing in the
                // calibration pose again. Re-checking a live session every five
                // seconds only replaced a working "已校准" line with a failure
                // message that had already been solved, which made the panel
                // read as broken while the avatar was moving.
                if (!Calibrated || IsCalibrationPose(body))
                {
                    string reason = CalibrationIssue(body);
                    if (reason != null || !IsCalibrationPose(body) || !Calibrate(body))
                    {
                        if (!Calibrated)
                        {
                            calibrationMessage = "自动校准失败：" + (reason ?? "请面向摄像头双臂平举");
                            calibrationMessageUntil = nextCalibrationAt;
                        }
                    }
                    else { calibrationMessage = null; calibrationMessageUntil = 0; }
                }
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
            for (int i = 0; i < RequiredSegmentCount; i++)
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
            // The hand basis needs the same frame change the body directions
            // get. Both depths are the direction their owner faces - the sensor
            // frame's is where the person looks, the model frame's is where the
            // avatar looks - so the rotation that carries one onto the other,
            // with the shoulders as the common reference, is the whole of it.
            // What is left over (`facing`) is the avatar turning during the
            // match, applied per frame next to it.
            liveFacing = Quaternion.identity;
            sensorToModel = Quaternion.LookRotation(modelDepth, Vector3.up) *
                            Quaternion.Inverse(Quaternion.LookRotation(sourceDepth, Vector3.up));
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
            // The same rotation the hands go through, not a second opinion on it.
            //
            // This used to be written out by hand as
            //     modelRight * (offset . sourceRight) + up * offset.y
            //     - modelDepth * (offset . sourceDepth)
            // which maps the person's right onto the avatar's right, up onto up,
            // and their *forward onto the avatar's backward*. That is a reflection,
            // not a rotation: it preserves `right` and flips `depth`, which no
            // orientation of two bodies can do. Every bone was then aimed along a
            // mirrored direction while the palm basis was mapped by the rotation in
            // `sensorToModel` - so the arm and the hand hanging off it lived in two
            // frames a mirror apart, and the two only agree for motion that has no
            // forward component. Reaching forward, and above all crossing the arms,
            // is exactly where that shows: on the 2026-11-11 recording the user
            // holds both forearms in front of the chest and the avatar answers by
            // folding them up and back, which reads as "it moves the opposite way
            // to me".
            //
            // One rotation, one frame: `sensorToModel` already maps sourceRight to
            // modelRight, up to up and sourceDepth to modelDepth, and the receiver
            // turns the whole pose by `facing` on top of it.
            return sensorToModel * offset;
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
            for (int i = 0; i < RequiredSegmentCount; i++)
                for (int n = 1; n <= 2; n++)
                {
                    int id = segments[i,n];
                    if (checkedJoint[id]) continue;
                    checkedJoint[id] = true;
                    var joint = body.Joint((JointType)id);
                    if (joint == null || joint.status == 0) missing.Add(jointNames[id]);
                }
            if (missing.Count > 0) return "未追踪：" + string.Join("、", missing.ToArray());
            for (int i = 0; i < RequiredSegmentCount; i++)
            {
                Vector3 v;
                if (!Direction(body, segments[i,1], segments[i,2], out v))
                    return jointNames[segments[i,1]] + "与" + jointNames[segments[i,2]] + "位置过近";
            }
            // Legs are optional. Record what was skipped so the panel can say so
            // instead of silently pinning the legs to the bind pose.
            legNote = null;
            for (int i = RequiredSegmentCount; i < segments.GetLength(0); i++)
            {
                string missingLeg = null;
                for (int n = 1; n <= 2; n++)
                {
                    var joint = body.Joint((JointType)segments[i,n]);
                    if (joint == null || joint.status == 0) missingLeg = jointNames[segments[i,n]];
                }
                if (missingLeg != null) legNote = legNote == null ? missingLeg : legNote + "、" + missingLeg;
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

        // Shows the received hand skeleton in the palm plane: proof that the 21
        // joints arrive attached to this body, independent of the avatar rig.
        void DrawHandPreview(Rect area)
        {
            GUI.Box(area, "手部骨架（掌心平面）");
            var frame = handReceiver != null && handReceiver.IsReceiving ? handReceiver.LatestFrame : null;
            if (frame == null || frame.hands == null || frame.hands.Length == 0)
            {
                GUI.Label(new Rect(area.x + 10, area.y + 28, area.width - 20, 40), "等待手部数据");
                return;
            }
            float slotWidth = (area.width - 24) / Mathf.Max(1, frame.hands.Length);
            for (int index = 0; index < frame.hands.Length; index++)
            {
                var hand = frame.hands[index];
                if (hand == null || !hand.HasSkeleton) continue;
                DrawHandPoints(new Rect(area.x + 12 + index * slotWidth, area.y + 24,
                    slotWidth - 8, area.height - 32), hand);
            }
        }

        void DrawHandPoints(Rect slot, HandEntry hand)
        {
            const float lowX = -0.9f, highX = 0.9f, lowY = -0.2f, highY = 2.3f;
            float scale = Mathf.Min(slot.width / (highX - lowX), slot.height / (highY - lowY));
            var origin = new Vector2(slot.center.x, slot.yMax - 4);
            var points = new Vector2[HandEntry.JointCount];
            for (int i = 0; i < points.Length; i++)
            {
                float x = hand.joints[i * 3], y = hand.joints[i * 3 + 1];
                points[i] = new Vector2(origin.x + x * scale, origin.y - (y - lowY) * scale);
            }
            Color tint = hand.IsLeft ? Color.cyan : new Color(1f, 0.72f, 0.2f);
            for (int finger = 0; finger < handChains.Length; finger++)
            {
                var chain = handChains[finger];
                for (int k = 0; k + 1 < chain.Length; k++)
                    DrawLine(points[chain[k]], points[chain[k + 1]], tint);
            }
            Color old = GUI.color;
            GUI.color = tint;
            for (int i = 0; i < points.Length; i++)
                GUI.DrawTexture(new Rect(points[i].x - 2, points[i].y - 2, 4, 4), Texture2D.whiteTexture);
            GUI.color = old;
            GUI.Label(new Rect(slot.x, slot.y - 2, slot.width, 20), hand.IsLeft ? "左手" : "右手");
        }

        static void DrawLine(Vector2 from, Vector2 to, Color color)
        {
            Vector2 delta = to - from;
            if (delta.sqrMagnitude < 1f) return;
            var matrix = GUI.matrix;
            Color old = GUI.color;
            GUIUtility.RotateAroundPivot(Mathf.Atan2(delta.y, delta.x) * Mathf.Rad2Deg, from);
            GUI.color = color;
            GUI.DrawTexture(new Rect(from.x, from.y - 1, delta.magnitude, 2), Texture2D.whiteTexture);
            GUI.color = old;
            GUI.matrix = matrix;
        }

        void LateUpdate()
        {
            if (game == null || actor == null || game.SelectionOpen) return;
            // The body pose needs a calibration; the hands do not. They are an
            // independent observation - 21 joints in the wrist's own frame plus
            // the palm's basis - so the only thing they borrow from the body is
            // where the wrist happens to be right now. Gating them on
            // `Calibrated` is what made a 74 second session of correctly
            // detected hands do nothing at all on screen: the body never held
            // the T-pose, so `ApplyHands` was never reached.
            SkeletonBody body = null;
            if (Calibrated && receiver.IsReceiving && receiver.LatestFrame.bodies.Length > 0)
            {
                var candidate = receiver.LatestFrame.bodies[0];
                if (candidate.id == CalibratedBodyId && receiver.LatestFrame.session == calibratedSession)
                    body = candidate;
            }
            if (body != null) ApplyBodyPose(body);
            ApplyHands();
        }

        void ApplyBodyPose(SkeletonBody body)
        {
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
            // The hands only borrow the wrist's *position* from the body, so
            // whatever turn the body got has to be given to them explicitly.
            liveFacing = facing;
            // Reorient the entire model, including bones that are not tracked.
            bones[0].rotation = facing * bindRotations[0];
            for (int i = 0; i < segments.GetLength(0); i++)
            {
                int bone = segments[i,0]; Vector3 current;
                if (!valid[bone] || !Direction(body, segments[i,1], segments[i,2], out current)) continue;
                Quaternion desired = facing * Quaternion.FromToRotation(baseline[bone], current) * bindRotations[bone];
                liveRotations[bone] = Quaternion.Slerp(liveRotations[bone], desired, t);
                // 7 and 10 are the wrists. Keep their accumulated rotation
                // current so handing them back does not jump, but do not write
                // them: the palm's own orientation is measured, and a body
                // rotation that overwrites it every frame would leave the hand
                // following the tracked palm only a fraction of the way.
                if (!(actor.wristOverridden && (bone == 7 || bone == 10)))
                    bones[bone].rotation = liveRotations[bone];
            }
            // The sensor foot joints are intentionally unused. Override the
            // replay pose so each model shin points straight down from its knee.
            PointShinDown(bones[12], bones[13]);
            PointShinDown(bones[16], bones[17]);
            UpdatePlayerView(body);
        }

        void ApplyHands()
        {
            if (actor == null) return;
            var frame = handReceiver != null && handReceiver.IsReceiving ? handReceiver.LatestFrame : null;
            if (frame == null || frame.hands == null || frame.hands.Length == 0)
            {
                handsDriving = false;
                bool recent = Time.unscaledTime - lastHandApplyAt <= 1f;
                actor.handPoseOverridden = recent;
                actor.wristOverridden = recent;
                // Nothing has ever been driven here, so the avatar's own hand
                // pose belongs to the game: leave it alone instead of easing it
                // to a bind pose nobody asked for.
                if (!recent) return;
                // Tracking lost: ease both hands back to the bind pose instead of
                // freezing them mid-gesture.
                actor.RelaxHand(true);
                actor.RelaxHand(false);
                return;
            }
            if (handPoints == null) handPoints = new Vector3[HandEntry.JointCount];
            bool left = false, right = false, measured = false;
            foreach (var hand in frame.hands)
            {
                if (hand.HasSkeleton)
                {
                    for (int i = 0; i < HandEntry.JointCount; i++)
                        handPoints[i] = new Vector3(hand.joints[i * 3], hand.joints[i * 3 + 1], hand.joints[i * 3 + 2]);
                    Vector3 hx, hy, hz;
                    HandBasis(hand, out hx, out hy, out hz);
                    // Bring the palm into the frame the body is posed in. The
                    // sensor sees the person from the front; the avatar is
                    // turned to the opponent, and in this match that is a right
                    // angle. Skipping it leaves the hand flat to the screen
                    // while the arm points elsewhere - the wrist is bent 90
                    // degrees and the palm looks like it is facing the camera
                    // on purpose.
                    Quaternion toModel = liveFacing * sensorToModel;
                    hx = toModel * hx;
                    hy = toModel * hy;
                    hz = toModel * hz;
                    actor.ApplyHandSkeleton(hand.IsLeft, handPoints, hx, hy, hz);
                    if (hand.HasBasis) measured = true;
                    if (hand.IsLeft) { left = true; lastLeftHandAt = Time.unscaledTime; }
                    else { right = true; lastRightHandAt = Time.unscaledTime; }
                }
            }
            // A hand that drops out of the packet for a frame or two has not left
            // the frame - it is behind the other arm, or the detector lost it
            // while the palms overlap. Easing it to the bind pose on that frame
            // and back onto the tracked pose on the next one is the flap that
            // reads as "it does the opposite of my hand": the crossed-arms pose
            // in the 2026-11-11 recording lost both hands for two and a half
            // seconds, and every one of those frames the receiver was posing the
            // hand from somewhere else. Hold it instead, and only give up after
            // HandGrace - the sender already re-sends a solved pose for HAND_HOLD
            // (0.8 s) before a hand stops appearing at all.
            if (!left && Time.unscaledTime - lastLeftHandAt <= HandGrace) left = true;
            if (!right && Time.unscaledTime - lastRightHandAt <= HandGrace) right = true;
            if (!left) actor.RelaxHand(true);
            if (!right) actor.RelaxHand(false);
            handsDriving = left || right;
            // Fingers belong to the tracker from here on. The replay writes its
            // own constant curl into the same fifteen bones on every frame, and
            // the aim only closes 1 - exp(-18 * dt) of the gap per frame - 13 %
            // at 130 fps. Against a write that lands first every frame that is
            // not a filter, it is an 87 % follow limit.
            actor.handPoseOverridden = handsDriving;
            // The wrist is only taken over when there is a measured palm frame
            // to aim it at. Without one the replay keeps posing the arm and the
            // hand has to stay with it.
            actor.wristOverridden = handsDriving && measured;
            // Version 1 senders only have curls; keep them working as a fallback.
            if (left || right)
            {
                lastHandApplyAt = Time.unscaledTime;
                return;
            }
            if (handCurls == null) handCurls = new float[30];
            for (int i = 0; i < handCurls.Length; i++) handCurls[i] = -1f;
            foreach (var hand in frame.hands)
            {
                if (hand.curls == null) continue;
                int offset = hand.IsLeft ? 0 : 15;
                for (int i = 0; i < 15; i++) handCurls[offset + i] = hand.curls[i];
            }
            actor.ApplyFingerCurls(handCurls);
            actor.handPoseOverridden = true;
            handsDriving = true;
            lastHandApplyAt = Time.unscaledTime;
        }

        void HandBasis(HandEntry hand, out Vector3 x, out Vector3 y, out Vector3 z)
        {
            x = Vector3.zero; y = Vector3.zero; z = Vector3.zero;
            if (!hand.HasBasis || receiver == null) return;
            Transform frame = receiver.transform;
            x = frame.TransformDirection(receiver.ToLocalDirection(hand.BaseX));
            y = frame.TransformDirection(receiver.ToLocalDirection(hand.BaseY));
            z = frame.TransformDirection(receiver.ToLocalDirection(hand.BaseZ));
            // ToLocalDirection mirrors x alone when mirrorX is on, which would
            // flip the hand's chirality; mirroring z as well restores a
            // right-handed frame so LookRotation stays meaningful.
            if (receiver.mirrorX) z = -z;
            if (flipPalmNormal)
            {
                // Swap palm and back of hand while keeping the frame
                // right-handed: flipping z alone would mirror the hand.
                x = -x; z = -z;
            }
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

        static string HandNumber(HumanoidReplay hand, bool isLeft, bool aim)
        {
            if (hand == null) return "-";
            return (aim ? hand.HandAimError(isLeft) : hand.HandFingerBend(isLeft)).ToString("F0");
        }

        /// <summary>
        /// How far the sensor's forward is turned away from the model's, in
        /// degrees. This is the twist the wrist would carry if the hand basis
        /// were used in the sensor frame: about 90 when the avatar fights side
        /// on to the camera, 180 when it faces straight away.
        /// </summary>
        float FrameYawDegrees()
        {
            if (sourceDepth.sqrMagnitude < 1e-6f || modelDepth.sqrMagnitude < 1e-6f) return 0f;
            return Vector3.SignedAngle(sourceDepth, modelDepth, Vector3.up);
        }

        /// <summary>
        /// Writes a one-second snapshot to Library/AstraLiveStatus.txt. When the
        /// panel looks empty this file answers "did the socket bind, is data
        /// arriving, is the game found" without needing a screenshot.
        /// </summary>
        void WriteStatus()
        {
            if (receiver == null || Time.unscaledTime < nextStatusWriteAt) return;
            nextStatusWriteAt = Time.unscaledTime + 1f;
            try
            {
                string text =
                    "time=" + DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss") + "\n" +
                    "scene=" + UnityEngine.SceneManagement.SceneManager.GetActiveScene().name + "\n" +
                    "body.listening=" + receiver.IsListening + " receiving=" + receiver.IsReceiving +
                    " frames=" + receiver.AcceptedFrames + " error=" + (receiver.LastError ?? "-") + "\n" +
                    "hand.listening=" + (handReceiver != null && handReceiver.IsListening) +
                    " receiving=" + (handReceiver != null && handReceiver.IsReceiving) +
                    " frames=" + (handReceiver != null ? handReceiver.AcceptedFrames : 0) + "\n" +
                    "game=" + (game != null) + " ready=" + (game != null && game.Ready) +
                    " selectionOpen=" + (game != null && game.SelectionOpen) +
                    " actor=" + (actor != null) + " calibrated=" + Calibrated + "\n" +
                    "hands.ready=" + (actor != null && actor.HandsReady) +
                    " driving=" + handsDriving +
                    " handBones=" + (actor != null ? actor.HandBoneCount : 0) +
                    " curlBones=" + (actor != null ? actor.CurlBoneCount : 0) +
                    " rollL=" + (actor != null ? actor.HandRollDegrees(true).ToString("F0") : "-") +
                    " rollR=" + (actor != null ? actor.HandRollDegrees(false).ToString("F0") : "-") +
                    " aimL=" + HandNumber(actor, true, true) + " aimR=" + HandNumber(actor, false, true) +
                    " bendL=" + HandNumber(actor, true, false) + " bendR=" + HandNumber(actor, false, false) +
                    " handFrames=" + (handReceiver != null ? handReceiver.AcceptedFrames : 0) +
                    " frameYaw=" + FrameYawDegrees().ToString("F1") +
                    " legNote=" + (legNote ?? "-") + "\n" +
                    "status=" + status + "\n";
                File.WriteAllText(Path.GetFullPath(Path.Combine(Application.dataPath, "..", "Library", "AstraLiveStatus.txt")), text);
            }
            catch (Exception) { }
        }

        void OnGUI()
        {
            if (receiver == null)
            {
                GUI.Label(new Rect(20, 20, 420, 40), "Astra Live P1 缺少 AstraSkeletonReceiver 组件");
                return;
            }
            if (uiFont == null) uiFont = Font.CreateDynamicFontFromOSFont("Microsoft YaHei", 16);
            Font oldFont = GUI.skin.font;
            bool oldWrap = GUI.skin.label.wordWrap;
            if (uiFont != null) GUI.skin.font = uiFont;
            GUI.skin.label.wordWrap = true;
            float width = Mathf.Min(590, Screen.width - 24);
            GUI.Box(new Rect(12, 12, width, 266), "单摄像头 P1 控制 / 状态检查");
            string source;
            lock (messageLock) source = senderError ?? senderMessage;
            bool active = sender != null && !sender.HasExited;
            if (!active && sender == null && receiver.IsReceiving)
                source = "外部数据源（命令行里的 run.cmd 或发送程序）";
            if (!active && sender != null && !source.StartsWith("ERROR", StringComparison.OrdinalIgnoreCase)) source = "发送程序已退出，请检查摄像头或授权。";
            GUI.Label(new Rect(25, 40, width - 24, 25), "数据源：" + source);
            string connection = receiver.IsReceiving ?
                (receiver.LatestFrame.simulated ? "已收到模拟数据" : "已收到摄像头数据") :
                !receiver.IsListening ? "UDP 7001 未绑定（端口被占用）" : "已监听 7001，等待数据";
            GUI.Label(new Rect(25, 65, width - 130, 25), "连接：" + connection);
            if (GUI.Button(new Rect(width - 105, 63, 98, 24), "重连 UDP"))
            {
                receiver.Reconnect();
                if (handReceiver != null) handReceiver.Reconnect();
            }
            string bodyState = !receiver.IsListening ? "UDP 7001 未绑定" : !receiver.IsReceiving ? "已监听，等待数据" :
                receiver.LatestFrame.bodies.Length == 0 ?
                "未识别到人：请全身入镜、面向摄像头。" : "已识别 1 人，编号 " + receiver.SelectedBodyId;
            GUI.Label(new Rect(25, 90, width - 24, 25), "人体：" + bodyState);
            string pose = game == null || !game.Ready ? "等待游戏人物加载" : game.SelectionOpen ?
                "请先完成选角和场地选择" :
                Calibrated ? (legNote == null ? "已校准，控制 P1（战斗回放暂停）"
                    : "已校准（" + legNote + "未追踪，腿部保持站立）")
                : Time.unscaledTime < calibrationMessageUntil ? calibrationMessage
                : "双臂平举等待校准；手指不需要校准，已在工作";
            GUI.Label(new Rect(25, 115, width - 24, 25), "控制：" + pose);
            string handState = handReceiver == null ? "未接入" :
                !handReceiver.IsListening ? "UDP 7011 未绑定" :
                !handReceiver.IsReceiving ? "已监听 7011，未收到数据（tools\\hand_tracking\\run.cmd）" :
                handReceiver.LatestFrame.hands.Length == 0 ? "已连接，画面中无手" :
                actor == null || !actor.HandsReady ? "收到 " + handReceiver.LatestFrame.hands.Length + " 只手，但角色没有可用指骨" :
                (handsDriving ? "正在驱动 " : "已接入 ") + handReceiver.LatestFrame.hands.Length + " 只手（21 点骨架 + 腕部旋转，" +
                actor.HandBoneCount + " 根指骨）" +
                (handsDriving ? "　中指屈 " + HandNumber(actor, true, false) + "/" + HandNumber(actor, false, false) + "°" : "");
            GUI.Label(new Rect(25, 138, width - 140, 22), "手部：" + handState);
            if (GUI.Button(new Rect(width - 105, 136, 98, 24), flipPalmNormal ? "手掌：已反向" : "手掌：正常"))
            {
                flipPalmNormal = !flipPalmNormal;
                if (actor != null) actor.ResetHandRoll();
            }
            if (GUI.Button(new Rect(25, 166, 120, 35), "启动摄像头")) StartSender(false);
            if (GUI.Button(new Rect(155, 166, 120, 35), "启动模拟")) StartSender(true);
            if (GUI.Button(new Rect(285, 166, 120, 35), "停止数据源")) StopSender();
            string countdown = nextCalibrationAt < 0 ? "等待人体" : "下次校准 " + Mathf.CeilToInt(Mathf.Max(0, nextCalibrationAt - Time.unscaledTime)) + " 秒";
            GUI.Label(new Rect(415, 171, 155, 30), countdown);
            GUI.Label(new Rect(25, 208, width - 24, 46), "操作：选角色和场地 → 启动摄像头 → 双臂平举并等待自动校准。\n手指不需要校准：只要收到 7011 报文就在驱动。身体每 5 秒尝试一次，姿势不满足时保留上次校准。");
            var body = receiver.IsReceiving && receiver.LatestFrame.bodies.Length > 0 ? receiver.LatestFrame.bodies[0] : null;
            float previewHeight = Mathf.Clamp(Screen.height - 296, 150, 340);
            DrawPreview(new Rect(12, 286, Mathf.Min(width, 330), previewHeight), body);
            float handTop = 380f;
            DrawHandPreview(new Rect(355, handTop, Mathf.Max(150, width - 345),
                Mathf.Clamp(Screen.height - handTop - 16, 120, 210)));
            if (body != null && !Calibrated)
            {
                var issue = CalibrationIssue(body);
                GUI.Label(new Rect(355, 280, Mathf.Max(120, width - 345), 90), issue == null ? "关节点满足最低校准条件" : "校准检查：\n" + issue);
            }
            GUI.skin.font = oldFont;
            GUI.skin.label.wordWrap = oldWrap;
        }

        void OnDestroy()
        {
            if (live == this) live = null;
            StopSender();
            if (uiFont != null) Destroy(uiFont);
        }

        // Exiting Play mode must not leave the bridge this panel started running:
        // an orphan bridge used to keep the UDP ports pinned after the editor was
        // gone, which made every later Play fail to bind.
        void OnDisable() { if (live == this) StopSender(); }

        void OnApplicationQuit() { StopSender(); }
    }
}
