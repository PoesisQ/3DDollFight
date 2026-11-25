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
        /// <summary>
        /// Angle between the palm normal the sender measured and the direction
        /// the avatar is facing, in degrees. 0 means the palm points at the
        /// opponent, 90 means it is edge-on to them, 180 means the back of the
        /// hand does. Shown in the panel because "the hand is 90 degrees out"
        /// is not something a screenshot can settle: this number can.
        /// </summary>
        float palmOffsetDegrees = -1f;
        [Tooltip("Flip if a forward reach puts the avatar's arms behind its back.")]
        public bool flipArmDepth;
        public string status = "Waiting for game and camera";
        public bool Calibrated { get; private set; }
        public int CalibratedBodyId { get; private set; }
        private string calibratedSession;
        private DollFightDemo game;
        private HumanoidReplay actor;
        private readonly Quaternion[] bindRotations = new Quaternion[19];
        private readonly Quaternion[] liveRotations = new Quaternion[19];
        // Toe bone relative to its foot, as the model was built. The shoe is one
        // rigid piece there - a quarter of its contact patch is weighted to the
        // toe - so keeping this exact offset is what keeps the sole a sole once
        // the foot is aimed at the floor instead of at the replay clip's pose.
        private readonly Quaternion[] toeBindings = { Quaternion.identity, Quaternion.identity };
        // Ankle relative to its shin, as the model was built. The sensor reports
        // the ankle as a position and never as a rotation, so this is the only
        // ankle angle there is: without it a bound foot keeps whatever the
        // previous frame left behind while the leg swings away from it.
        private readonly Quaternion[] ankleBindings = { Quaternion.identity, Quaternion.identity };
        private readonly Vector3[] baseline = new Vector3[19];
        private Vector3 baseHip;
        private Vector3 sensorHip;
        private Vector3 liveHip;
        private Vector3 initialHip;
        // Ankle height of the pose the game spawned the character in. That pose
        // was placed with its shoes on the floor, so keeping the ankles there is
        // a usable ground reference when the shoe surface cannot be measured.
        private float initialAnkleY;
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
            {11,10,11},{15,13,14},
            // The shins have a tracked joint at both ends - the knee above and
            // the ankle below - so their direction is measured, not invented.
            // Aiming each one at its own ankle is what lets a crouch keep its
            // knee angle: pinning it vertical instead swings the ankle under the
            // knee and drives the foot into the floor.
            {12,11,12},{16,14,15}
        };
        // Torso and arms must be solvable before calibrating. The four leg rows
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
        /// <summary>
        /// The match starts the camera by itself, because the panel that used to
        /// hold the button is now hidden. This process is <c>run.py</c>, which in
        /// turn owns the bridge; killing only the interpreter would leave the
        /// bridge holding the camera, so <see cref="StopPipeline"/> kills the
        /// whole tree.
        /// </summary>
        [Tooltip("Launch the hand pipeline (bridge + preview window) when the match starts.")]
        public bool autoStartPipeline = true;
        [Tooltip("Draw the status panel. F1 toggles it; off by default so it cannot cover the fight.")]
        public bool showDebugPanel;
        private System.Diagnostics.Process pipeline;
        private bool pipelineStarted;
        private string pipelineMessage = "未启动";
        // The bridge binds this itself - it is the exe's default, and
        // StartPipeline does not pass --color-port. Used only to tell whether a
        // leftover process is sitting on the port this session needs.
        private const int ColourPort = 7005;
        private readonly object messageLock = new object();
        private string senderMessage = "未启动";
        private string senderError;
        private const float CalibrationInterval = 5f;
        private float nextCalibrationAt = -1f;
        // A session that never holds the T-pose used to sit on the replay clip
        // forever while the hands worked, which reads as "the body is bound and
        // the character stands wrong" - the clip's own stance, including a pair
        // of shoes rolled a long way onto their edges. After this long in front
        // of the sensor, bind from the stance the person is already in instead.
        private const float StanceBindDelay = 6f;
        private float bodySeenSince = -1f;
        /// <summary>True when the current bind came from a stance, not a T-pose.</summary>
        private bool stanceBound;
        private float calibratedAt = -100f;
        // Upper bound on the hip lift that keeps the shoes out of the floor. A
        // real crouch shortens the legs as it lowers the hip, so this only ever
        // pays out the residual; the cap is there so a bad sole measurement
        // cannot float the whole character.
        private const float maxSoleLift = 0.08f;
        // The same residual in the other direction: a shoe hovering just above
        // the floor is the model's leg length, not a jump. Anything larger is
        // left alone so a raised foot is not pulled back down.
        private const float maxSoleDrop = 0.04f;
        // How close to the floor a shoe has to be before its angle is taken to
        // mean something. Above this the foot is mid-step and its angle is the
        // animation, not an error.
        private const float GroundedBand = 0.03f;
        // How far a planted shoe may be from flat and still be levelled. Past
        // this the sole is not resting on the floor at all - it is a kick, a
        // stretch, or a bad fit - and aiming it down from there rotates the
        // shoe right past its side, which is what turned feet over.
        private const float MaxSoleTilt = 65f;
        /// <summary>Hip correction applied this frame to plant the shoes, in metres.</summary>
        private float soleLift;
        /// <summary>Largest bend the toe bones had to give back this frame, in degrees.</summary>
        private float toeFix;
        /// <summary>
        /// How far the shoe was from flat before it was levelled, in degrees:
        /// the angle between the modelled sole carried into the pose and the
        /// floor. This is the clip's own roll, and it is what levelling removes.
        /// </summary>
        private float soleTilt;
        /// <summary>
        /// What an independent measurement of the shoe says is left over after
        /// levelling, in degrees. Nothing acts on it. Near zero means the
        /// modelled sole agreed with the mesh; a number as large as
        /// <see cref="soleTilt"/> means the modelled sole is wrong, not the
        /// levelling - the one failure this code cannot see by itself.
        /// </summary>
        private float soleResidual;
        /// <summary>
        /// Turn about the floor that levelling the shoe would have introduced,
        /// in degrees, before it was undone. This is the pigeon-toed angle: it
        /// is what the shortest rotation between "sole is at an angle" and "sole
        /// is flat" does to the direction the foot points.
        /// </summary>
        private float soleYaw;
        /// <summary>Feet that were in the air this frame and left to the pose.</summary>
        private bool soleAirLeft, soleAirRight;
        // The loader only builds a sole sampler for prefab bodies. A .vrm posed
        // live needs one just as much: straightening the legs moves the shoes,
        // and without a measurement there is nothing to keep them off the floor.
        private AvatarSoleContact liveSoles;
        private HumanoidReplay liveSolesOwner;
        // How far an elbow may lead its own hand towards the avatar's front.
        // As a direction cosine: 0.30 is about 17 degrees, and a hand that is
        // itself in front of the shoulder spends more of the budget. The arm
        // segment is a straight line from a tracked shoulder to a tracked elbow,
        // and the SDK's elbow is the weakest joint it reports - inferred, not
        // measured, and biased forward whenever the arm is anywhere near the
        // torso. See BesideHand.
        private const float ArmForwardSlack = 0.30f;
        /// <summary>Largest amount of forward elbow this frame that BesideHand had to remove.</summary>
        private float armPush;
        // A body that vanishes for a frame or two is a detection gap, not a
        // person leaving. Throwing the calibration away for it meant every such
        // gap needed another T-pose to recover from.
        private const float BodyGrace = 2f;
        private float lastBodySeenAt = -100f;
        /// <summary>
        /// The last frame that actually carried a body, and when it arrived.
        ///
        /// The sensor reports one body in about one frame in six: it drops the
        /// skeleton whenever a limb crosses the torso or the person shifts
        /// weight, and picks it up again a frame or two later. The uncalibrated
        /// path used to reset its stopwatch on every empty frame, so
        /// <see cref="StanceBindDelay"/> seconds of continuous detection could
        /// never accumulate and a whole recording went by on the replay clip
        /// with the person standing in front of the camera. Holding the last
        /// body across a gap - the same grace the calibrated path already had -
        /// is what lets that stopwatch reach six.
        /// </summary>
        private SkeletonFrame lastBodyFrame;
        private float lastBodyFrameAt = -100f;
        private bool handsDriving;
        private float lastHandApplyAt = -100f;
        // Per hand, not per pair: one hand leaving the packet says nothing about
        // the other, and the pair-wide timestamp this used to check made a single
        // lost hand relax while its partner carried on being tracked.
        private float lastLeftHandAt = -100f;
        private float lastRightHandAt = -100f;
        // Crossed forearms are the one pose a single camera cannot keep: both
        // palms overlap in the picture, MediaPipe drops them together, and the
        // 2026-11-11 14:45 clip has 2.4 s of no hands at all in the middle of the
        // cross. Any window shorter than that turns the cross into "the hands
        // vanish and come back", because the receiver lets go, the hand eases to
        // its bind pose and the next packet snaps it back. Hold the pose for
        // longer than the detector is known to lose it.
        private const float HandGrace = 2.5f;
        private float nextGameLookupAt;
        private float nextStatusWriteAt;
        private string calibrationMessage;
        private float calibrationMessageUntil;
        /// <summary>
        /// The first check <see cref="Calibrate"/> refused on, or null once a
        /// bind has succeeded. Several of those checks return false without
        /// touching <see cref="status"/> - the hip is the one that did - and a
        /// session that never binds then looks identical whether the person was
        /// out of frame or one joint was not tracked. This is what tells them
        /// apart in the status file.
        /// </summary>
        private string calibrateNote;
        private string legNote;
        private Font uiFont;
        private Font badgeFont;
        private GUIStyle badgeStyle;
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
            var exe = BridgePath();
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

        /// <summary>Path of the interpreter that runs <c>run.py</c>.</summary>
        string PipelinePython()
        {
            var root = Path.GetFullPath(Path.Combine(Application.dataPath, "../.."));
            return Path.Combine(root, "tools", "hand_tracking", ".venv", "Scripts", "python.exe");
        }

        /// <summary>
        /// Starts <c>run.py --start-bridge --preview</c> once per session.
        /// run.py owns both the bridge and the preview window, so this replaces
        /// the old pair of steps ("press 启动摄像头", then double-click run.cmd)
        /// with a single process that the match launches by itself.
        /// </summary>
        public void StartPipeline()
        {
            if (pipeline != null && !pipeline.HasExited) return;
            var root = Path.GetFullPath(Path.Combine(Application.dataPath, "../.."));
            var folder = Path.Combine(root, "tools", "hand_tracking");
            var python = PipelinePython();
            var script = Path.Combine(folder, "run.py");
            if (!File.Exists(python))
            {
                pipelineMessage = "缺少 Python 环境，请先运行 tools\\hand_tracking\\install.cmd";
                UnityEngine.Debug.LogWarning("Astra 摄像头未启动：" + pipelineMessage);
                return;
            }
            if (!File.Exists(script))
            {
                pipelineMessage = "找不到 tools\\hand_tracking\\run.py";
                UnityEngine.Debug.LogWarning("Astra 摄像头未启动：" + pipelineMessage);
                return;
            }
            // Whatever an earlier session left behind still owns the camera and
            // port 7005. A bridge started on top of it dies with "Cannot bind
            // color port 7005", and the leftover keeps publishing frames with no
            // body in them - which looks exactly like "the body skeleton
            // disappeared". Clear the ground before starting, not after failing.
            StopOrphanedPipeline(python);
            try
            {
                pipeline = new System.Diagnostics.Process();
                pipeline.StartInfo = new ProcessStartInfo(python, "-u \"" + script + "\" --start-bridge --preview")
                {
                    WorkingDirectory = folder,
                    UseShellExecute = false,
                    // A console window is wanted: it carries the fps line and the
                    // pairing warnings that make a bad run diagnosable.
                    CreateNoWindow = false
                };
                pipeline.Start();
                pipelineMessage = "已启动摄像头与预览";
            }
            catch (Exception e)
            {
                pipelineMessage = "启动失败：" + e.Message;
                if (pipeline != null) { pipeline.Dispose(); pipeline = null; }
            }
        }

        public void StopPipeline()
        {
            if (pipeline != null)
            {
                int id = -1;
                try { if (!pipeline.HasExited) id = pipeline.Id; }
                catch (InvalidOperationException) { }
                if (id > 0)
                {
                    // /T reaches the bridge that python spawned; without it the
                    // camera stays claimed until the editor is closed.
                    try
                    {
                        var kill = System.Diagnostics.Process.Start(new ProcessStartInfo("taskkill", "/PID " + id + " /T /F")
                        {
                            UseShellExecute = false,
                            CreateNoWindow = true
                        });
                        if (kill != null) kill.WaitForExit(3000);
                    }
                    catch (Exception) { }
                    // taskkill is the only handle on the grandchild. If it is not
                    // available, at least take the interpreter down.
                    try { if (!pipeline.HasExited) pipeline.Kill(); }
                    catch (Exception) { }
                }
                try { pipeline.Dispose(); }
                catch (Exception) { }
            }
            pipeline = null;
            pipelineStarted = false;
            pipelineMessage = "已停止";
            // run.py can already be gone while the bridge it spawned lives on,
            // and then there is no tree left to walk. Sweep by identity too.
            StopOrphanedPipeline(PipelinePython());
        }

        void WatchPipeline()
        {
            if (pipeline == null) return;
            try
            {
                if (!pipeline.HasExited) return;
                pipelineMessage = "摄像头进程已退出（代码 " + pipeline.ExitCode + "）";
                // The panel is hidden by default, so a silent exit would look
                // like "the preview never opened". Say it in the console too.
                UnityEngine.Debug.LogError("Astra " + pipelineMessage + "。按 F1 查看状态，或点「重启摄像头」。");
                pipeline.Dispose();
                pipeline = null;
                // Exiting early leaves its bridge holding the camera for every
                // later session, so take it down with the interpreter.
                StopOrphanedPipeline(PipelinePython());
            }
            catch (InvalidOperationException) { }
        }

        /// <summary>
        /// Ends a pipeline that outlived the process that started it.
        ///
        /// run.py can die - camera lost, bridge failed to bind - while the
        /// bridge it spawned keeps running and holding both the camera and port
        /// 7005. The next session's bridge then fails to bind, and the leftover
        /// goes on publishing frames with an empty body list, which reads as
        /// "the body skeleton disappeared and only the fingers are left". The
        /// tracked child is no help: once it has exited there is no id to walk
        /// from, so this sweeps by identity - this project's own interpreter,
        /// and every bridge built from this project.
        /// </summary>
        static void StopOrphanedPipeline(string python)
        {
            try
            {
                foreach (var process in Process.GetProcessesByName("python"))
                {
                    try
                    {
                        if (string.Equals(process.MainModule.FileName, python, StringComparison.OrdinalIgnoreCase))
                            KillProcess(process);
                    }
                    catch (Exception) { }
                    finally { process.Dispose(); }
                }
            }
            catch (Exception) { }
            // Every bridge of this build goes, not only one sitting on the
            // colour port. A leftover started without --color-port holds no
            // port that can be probed, but it still opens the camera, and the
            // SDK serves the body stream to one reader only: the session's own
            // bridge then publishes an empty body list for its whole life while
            // the orphan publishes the person. That is the split this project
            // kept hitting - Unity reporting zero bodies at the same moment the
            // preview window drew nineteen confident joints.
            string exe = BridgePath();
            try
            {
                foreach (var process in Process.GetProcessesByName("AstraUnityBridge"))
                {
                    try
                    {
                        bool ours;
                        try { ours = string.Equals(process.MainModule.FileName, exe, StringComparison.OrdinalIgnoreCase); }
                        // A path that cannot be read is most likely one of ours
                        // anyway, so fall back to the port it would be blocking.
                        catch (Exception) { ours = ColourPortTaken(); }
                        if (ours) KillProcess(process);
                    }
                    catch (Exception) { }
                    finally { process.Dispose(); }
                }
            }
            catch (Exception) { }
            // The kernel drops the listener when the last handle closes. Waiting
            // for it beats starting the new bridge into the same bind failure.
            for (int i = 0; i < 10 && ColourPortTaken(); i++) System.Threading.Thread.Sleep(100);
        }

        /// <summary>Path of the sender this project builds.</summary>
        static string BridgePath()
        {
            var root = Path.GetFullPath(Path.Combine(Application.dataPath, "../.."));
            return Path.Combine(root, "integrations/astra-unity-bridge/build/bin/Release/AstraUnityBridge.exe");
        }

        /// <summary>True when something is listening on the bridge's colour port.</summary>
        static bool ColourPortTaken()
        {
            try
            {
                using (var client = new System.Net.Sockets.TcpClient())
                {
                    if (!client.ConnectAsync("127.0.0.1", ColourPort).Wait(200)) return false;
                    return client.Connected;
                }
            }
            catch (Exception) { return false; }
        }

        static void KillProcess(Process process)
        {
            try
            {
                if (process.HasExited) return;
                process.Kill();
                process.WaitForExit(2000);
            }
            catch (Exception) { }
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
            if (Input.GetKeyDown(KeyCode.F1)) showDebugPanel = !showDebugPanel;
            WatchPipeline();
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
                initialAnkleY = Mathf.Min(actor.Bones[13].position.y, actor.Bones[17].position.y);
                playerWorldCamera = playerBodyCamera = null;
            }
            game.playing = false; // Do not present prerecorded fighting events as live results.
            if (game.SelectionOpen) { status = "Choose characters and arena, then press C in T-pose"; return; }
            // The match is on: bring the camera up without being asked. Starting
            // it here rather than in Start() means the sensor is not held open
            // while someone is still browsing characters.
            if (autoStartPipeline && !pipelineStarted)
            {
                pipelineStarted = true;
                StartPipeline();
            }
            var frame = receiver.LatestFrame;
            bool frameHasBody = frame != null && frame.bodies.Length > 0;
            if (frameHasBody)
            {
                lastBodyFrame = frame;
                lastBodyFrameAt = Time.unscaledTime;
            }
            // While uncalibrated, a gap in the body stream is bridged with the
            // last frame that had one. Skipping it here instead restarts the
            // stance stopwatch on every gap, and a body that arrives one frame
            // in six never gets six seconds of it.
            if (!frameHasBody && !Calibrated && lastBodyFrame != null &&
                Time.unscaledTime - lastBodyFrameAt < BodyGrace)
            {
                frame = lastBodyFrame;
                frameHasBody = true;
            }
            if (!receiver.IsReceiving || frame == null || !frameHasBody)
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
                Calibrated = false; nextCalibrationAt = -1f; bodySeenSince = -1f;
                status = "Waiting for tracked person"; return;
            }
            lastBodySeenAt = Time.unscaledTime;
            var body = frame.bodies[0];
            if (Calibrated && (body.id != CalibratedBodyId || calibratedSession != frame.session))
            { Calibrated = false; nextCalibrationAt = -1f; }
            if (bodySeenSince < 0f) bodySeenSince = Time.unscaledTime;
            if (nextCalibrationAt < 0) nextCalibrationAt = Time.unscaledTime + CalibrationInterval;
            if (Time.unscaledTime >= nextCalibrationAt)
            {
                nextCalibrationAt = Time.unscaledTime + CalibrationInterval;
                bool tpose = IsCalibrationPose(body);
                bool stance = !Calibrated && Time.unscaledTime - bodySeenSince >= StanceBindDelay;
                // Only re-run the check when it can change the answer: while
                // uncalibrated, or when the person is actually standing in the
                // calibration pose again. Re-checking a live session every five
                // seconds only replaced a working "已校准" line with a failure
                // message that had already been solved, which made the panel
                // read as broken while the avatar was moving.
                if (!Calibrated || tpose)
                {
                    string reason = CalibrationIssue(body);
                    if (reason == null && (tpose || stance) && Calibrate(body, tpose))
                    { calibrationMessage = null; calibrationMessageUntil = 0; }
                    else if (!Calibrated)
                    {
                        float wait = Mathf.Max(0f, StanceBindDelay - (Time.unscaledTime - bodySeenSince));
                        calibrationMessage = reason != null ? "自动校准失败：" + reason
                            : stance ? "站姿绑定失败，请全身入镜"
                            : "双臂平举可校准，" + Mathf.CeilToInt(wait) + " 秒后按当前站姿绑定";
                        calibrationMessageUntil = nextCalibrationAt;
                    }
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
            return Calibrate(body, true);
        }

        /// <summary>
        /// Binds the avatar to the person.
        ///
        /// With <paramref name="useRestPose"/>, the avatar is first restored to
        /// its imported T-pose, which is the pose the person is asked to hold:
        /// their arms and the model's arms then mean the same thing, so every
        /// later direction is read against the model's own rest.
        ///
        /// Without it, the avatar keeps the pose it is already in - the replay
        /// clip's - and that becomes the reference instead. It is a worse
        /// mapping (the model's guard is not the person's stance), but it is
        /// the difference between following with a small offset and not
        /// following at all, and a session that never holds the T-pose used to
        /// fail exactly that way.
        /// </summary>
        bool Calibrate(SkeletonBody body, bool useRestPose)
        {
            if (actor == null || body == null || !body.IsTracked) { calibrateNote = "no tracked body"; return false; }
            for (int i = 0; i < RequiredSegmentCount; i++)
            {
                Vector3 direction;
                if (!Direction(body, segments[i,1], segments[i,2], out direction))
                {
                    calibrateNote = "segment " + i + " (" + jointNames[segments[i,1]] + "->" + jointNames[segments[i,2]] + ")";
                    status = "Calibration needs all main joints tracked"; return false;
                }
            }
            var hip = body.Joint(JointType.BaseSpine);
            if (hip == null || hip.status < 1)
            {
                calibrateNote = "hip " + (hip == null ? "missing" : "status " + hip.status);
                return false;
            }
            var bones = actor.Bones;
            // Preserve the game position when restoring the imported T-pose. A
            // stance bind has no pose to restore: the pose on screen is the
            // reference, and moving it would be the jump this mode exists to
            // avoid.
            Vector3 anchor = useRestPose ? (Calibrated ? liveHip : initialHip) : bones[0].position;
            if (useRestPose)
            {
                actor.RestoreBindPose();
                bones[0].position = anchor;
            }
            // The bind pose has straighter legs than whatever clip the model was
            // spawned in, so the hip height the game left behind is too low for
            // it: the shoes end up under the floor. Measure the shoe surface in
            // the restored pose and plant it on the actor's own floor plane
            // instead of trusting that hip height.
            var soles = Soles();
            if (soles != null)
            {
                float lowest = soles.LowestSole();
                if (lowest > -0.5f && lowest < 0.5f)
                {
                    anchor.y += FloorHeight() - lowest;
                    bones[0].position = anchor;
                }
            }
            Vector3 shoulders = bones[8].position - bones[5].position;
            shoulders.y = 0;
            Vector3 opponentDirection;
            if (shoulders.sqrMagnitude > 0.0001f && DirectionToOpponent(anchor, out opponentDirection))
            {
                Vector3 forward = Vector3.Cross(shoulders.normalized, Vector3.up);
                bones[0].rotation = FaceDirection(forward, opponentDirection) * bones[0].rotation;
            }
            for (int i = 0; i < 19; i++) { bindRotations[i] = bones[i].rotation; liveRotations[i] = bones[i].rotation; valid[i] = false; }
            toeBindings[0] = Quaternion.Inverse(bones[13].rotation) * bones[14].rotation;
            toeBindings[1] = Quaternion.Inverse(bones[17].rotation) * bones[18].rotation;
            ankleBindings[0] = Quaternion.Inverse(bones[12].rotation) * bones[13].rotation;
            ankleBindings[1] = Quaternion.Inverse(bones[16].rotation) * bones[17].rotation;
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
            {
                calibrateNote = "shoulders " + sourceRight.sqrMagnitude.ToString("F4") + "/" + modelRight.sqrMagnitude.ToString("F4");
                status = "Calibration needs separated shoulders"; return false;
            }
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
            Calibrated = true; bodySeenSince = -1f;
            calibrateNote = null;
            stanceBound = !useRestPose; calibratedAt = Time.unscaledTime;
            status = useRestPose ? "Live P1; replay combat paused" : "Live P1 (站姿绑定); replay combat paused";
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
            // Two senders, two conventions, and they are not the same one.
            //
            // The hand sender builds its axes in the *camera* frame and converts
            // them on the way out (`run.py: WIRE_TO_UNITY`), which was measured
            // against the avatar's own knuckle frame and lands on 0 degrees. The
            // body skeleton does not: it is the Astra SDK's joint positions passed
            // through untouched (`axisSigns` is 1,1,1), and that frame is the
            // sensor's, not Unity's.
            //
            // Which is why this map and `sensorToModel` are allowed to disagree
            // about depth. `sensorToModel` is the rotation that carries the
            // *hand*'s frame onto the model's; taking it for the body as well
            // (the 2026-11-11 15:20 commit) sends the arms behind the torso the
            // moment they reach forward, and reads on the 16:07 recording as "the
            // hand runs backwards and the arms fold in when I open them". The
            // torso and the hips barely move in depth in a standing session,
            // which is why only the arms showed it.
            //
            // So the body keeps its own map: right onto right, up onto up, and
            // the sensor's depth onto the model's *reversed*. Written as a
            // matrix that is a reflection (determinant minus one) - and it has to
            // be, because the two frames are mirror images of each other for the
            // body channel. A reflection maps directions correctly but would
            // mirror anything with a handedness, which is exactly why the palm
            // basis must not come through here.
            //
            // `flipArmDepth` exists because this is the kind of claim that is
            // cheaper to settle on the real camera than in a comment: press it
            // while reaching forward and the panel records which way was right.
            if (flipArmDepth) return sensorToModel * offset;
            return modelRight * Vector3.Dot(offset, sourceRight) +
                   Vector3.up * offset.y - modelDepth * Vector3.Dot(offset, sourceDepth);
        }

        /// <summary>
        /// Stops an upper arm from swinging across the chest while its own hand
        /// is still beside the hip.
        ///
        /// The arm segment is nothing but a line from a tracked shoulder to a
        /// tracked elbow, and of the two the elbow is the one the sensor guesses:
        /// it sits on or against the torso most of the time, so its depth comes
        /// from the tracker's own body model instead of from a measured surface,
        /// and the guess leans forward. When the person opens both arms the
        /// avatar answers by folding them in front of itself - which reads in the
        /// eye-height player view as "my own arm is in my face", while from
        /// behind the fight the same pose still looks like arms held out.
        ///
        /// The hand is not in that guess: it is the joint the hand tracker also
        /// sees, and it is what the arm has to serve. So the elbow may only lead
        /// the hand towards the avatar's front. A hand that really is out in
        /// front buys the elbow the room to follow it, and a punch - hand and
        /// elbow both forward - is left alone entirely.
        /// </summary>
        Vector3 BesideHand(SkeletonBody body, int bone, Vector3 direction)
        {
            bool left = bone == 5;
            var shoulder = body.Joint(left ? JointType.LeftShoulder : JointType.RightShoulder);
            var wrist = body.Joint(left ? JointType.LeftWrist : JointType.RightWrist);
            if (shoulder == null || wrist == null || shoulder.status < 1 || wrist.status < 1) return direction;
            Vector3 toHand = receiver.ToWorldPosition(wrist.position) - receiver.ToWorldPosition(shoulder.position);
            if (toHand.sqrMagnitude < 0.0001f) return direction;
            // Same frame the segment directions live in, so the two can be
            // compared against one axis without a second set of books.
            toHand = MapSensorOffset(toHand).normalized;
            float handForward = Vector3.Dot(toHand, modelDepth);
            float allowed = ArmForwardSlack + Mathf.Max(0f, handForward);
            float forward = Vector3.Dot(direction, modelDepth);
            if (forward <= allowed) return direction;
            float excess = forward - allowed;
            if (excess > armPush) armPush = excess;
            Vector3 trimmed = direction - modelDepth * excess;
            // A guess that was almost entirely forward has nothing left once the
            // excess is gone. The hand is the one part of the arm two trackers
            // agree on, so point the arm at it instead of inventing a lean.
            return trimmed.sqrMagnitude < 0.09f ? toHand : trimmed.normalized;
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
            // A fixed number of pixels per metre, not a fit to this frame's
            // bounding box. Fitting the box made the whole skeleton shrink
            // whenever an arm went out to the side, and a shrunken skeleton
            // draws the two shins only a few pixels apart - which reads as the
            // legs having moved together when nothing about the legs changed.
            // This is a front view of a person measured in metres; the pose
            // should not be what sets the zoom.
            float scale = Mathf.Min(drawWidth / 1.9f, drawHeight / 2.2f);
            // Centred on the hips, so the body stays put while a hand moves.
            var center = visible[0]
                ? new Vector2(points[0].x, points[0].y)
                : new Vector2((minX + maxX) * 0.5f, (minY + maxY) * 0.5f);
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
            else PlantClipFeet();
            ApplyHands();
        }

        /// <summary>
        /// Puts the shoes the replay clip is wearing back on the floor.
        ///
        /// While no body is bound, the whole pose - feet included - comes from
        /// the clip, and this clip rolls its feet a long way onto their edges:
        /// measured at 17 to 29 degrees on the sparring take. That is the shoe
        /// standing on its heel with the toe in the air, and no amount of work
        /// on the bind helps, because every line of the bind is behind
        /// <see cref="Calibrated"/> and none of it runs.
        ///
        /// Levelling a shoe only needs the shoe: the sole plane is fitted once
        /// in the imported pose, and the toe offset is the one the model was
        /// built with. Neither depends on the person being bound, so the same
        /// pass can run here. Feet the clip has lifted are left to the clip -
        /// flattening a swinging shoe is what makes a walk look like a slide.
        /// </summary>
        void PlantClipFeet()
        {
            if (Soles() == null) return;
            PlantFeet(actor.Bones);
        }

        void ApplyBodyPose(SkeletonBody body)
        {
            var bones = actor.Bones;
            armPush = 0f;
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
                if (bone == 5 || bone == 8) current = BesideHand(body, bone, current);
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
            // The sensor foot joints are used through the shin rows above: knee
            // to ankle is a measured direction, so the knee angle is the
            // person's own. Only a leg that was never tracked at calibration
            // falls back to straight down - leaving it to the replay clip would
            // put a bent knee under a tracked thigh.
            if (!valid[12]) PointShinDown(bones[12], bones[13]);
            if (!valid[16]) PointShinDown(bones[16], bones[17]);
            PlantFeet(bones);
            UpdatePlayerView(body);
        }

        /// <summary>
        /// Keeps the shoes on their feet, and the ones on the floor flat.
        ///
        /// The sensor reports the ankle as a position and never as a rotation,
        /// so a bound foot has to be carried by its shin: <see cref="FollowAnkle"/>
        /// puts it back at the ankle angle the model was built with, every
        /// frame. That is what a kick needs - the leg swings, the shoe goes with
        /// it. Left out, the foot was only ever levelled, so the shoe stayed
        /// flat in world space while the leg went horizontal: the ankle read as
        /// broken, and the levelling pass that followed rotated an already
        /// detached shoe right past its side.
        ///
        /// A foot that is off the floor is not levelled at all. Its angle is
        /// the pose, not an error, and pinning it to a floor it is not touching
        /// is what flattens a step into a slide.
        ///
        /// A planted foot is levelled against the *modelled* sole - a constant
        /// vector in the foot bone's own frame, fitted once in the imported
        /// pose - and never against a plane re-fitted from the shoe's current
        /// position. That re-fit is what made standing worse than kicking on
        /// the 2026-11-25 12:01 recording: the shoe is measured in the very
        /// pose the error is in, so the fit reports the error back as if it
        /// were the target, the foot aims at it, and the roll grows. One
        /// rotation from a fixed reference is exact by construction; there is
        /// nothing left to converge on, and nothing to overshoot.
        ///
        /// Then the hips are moved by however far the lowest sole missed the
        /// actor's floor. Downwards only inside a small band: a shoe a couple of
        /// centimetres up is the model's leg being a different length from the
        /// person's, while a larger gap is a foot that is genuinely in the air.
        ///
        /// The toe bone is paired back to the levelled foot, because the shoe's
        /// contact patch is one rigid piece across both bones and only the foot
        /// is ours to aim.
        /// </summary>
        void PlantFeet(Transform[] bones)
        {
            var soles = Soles();
            toeFix = 0f;
            soleTilt = 0f;
            soleResidual = 0f;
            soleYaw = 0f;
            soleAirLeft = soleAirRight = false;
            float floor = FloorHeight();
            for (int side = 0; side < 2; side++)
            {
                int foot = side == 0 ? 13 : 17;
                // Hang the foot off its shin before anything is measured, so
                // the shoe starts from a real ankle instead of from whatever
                // angle the previous frame happened to leave behind.
                if (Calibrated) FollowAnkle(bones, side);
                // A foot this far off the floor is being lifted, not standing.
                bool planted = soles == null || soles.SoleHeight(side) - floor <= GroundedBand;
                if (!planted)
                {
                    if (side == 0) soleAirLeft = true; else soleAirRight = true;
                    // The ankle moved, so the toe has to move with it. The rest
                    // of the shoe's angle belongs to whoever posed the leg.
                    if (Calibrated) PairToe(bones, side);
                    continue;
                }
                Vector3 up;
                if (soles == null || !soles.TrySoleUp(side, out up)) continue;
                Vector3 sole = bones[foot].rotation * up;
                soleTilt = Mathf.Max(soleTilt, Vector3.Angle(sole, Vector3.up));
                // A sole that already lies along the floor needs nothing. A
                // sole pointing at the floor is a foot something turned over,
                // and no rotation gets it back that does not take the shoe past
                // its own side - <see cref="AimSole"/> refuses both.
                if (sole.y > 0.2f)
                    soleYaw = Mathf.Max(soleYaw, AimSole(bones[foot], bones[foot + 1], sole));
                PairToe(bones, side);
                // What is left, measured and reported - never acted on. If this
                // stays large while the lines above did nothing, the modelled
                // sole is the thing that is wrong, not the levelling.
                if (soles.TrySoleNormal(side, bones[foot].rotation * up, out Vector3 measured))
                    soleResidual = Mathf.Max(soleResidual, Vector3.Angle(measured, Vector3.up));
            }
            // With the shoe measured, plant its lowest point on the floor.
            // Without it, fall back to the ankle height the game spawned the
            // character with, which carried the same soles.
            soles?.Refresh();
            float gap = soles != null
                ? FloorHeight() - soles.LowestSole()
                : initialAnkleY - Mathf.Min(bones[13].position.y, bones[17].position.y);
            // Positive is under the floor. Lifting is unconditional up to the
            // cap; lowering only pays out a model/person leg-length mismatch and
            // never chases a foot that has left the ground.
            if (gap > 0.003f) soleLift = Mathf.Min(gap, maxSoleLift);
            else if (soles != null && gap < -0.005f) soleLift = Mathf.Max(gap, -maxSoleDrop);
            else soleLift = 0f;
            if (soleLift != 0f) bones[0].position += Vector3.up * soleLift;
        }

        /// <summary>
        /// Hangs the foot off its shin at the angle the model was built with.
        ///
        /// The sensor's ankle is a point, not a joint: no rotation is reported
        /// for it, so an ankle angle has to be assumed. The modelled one is the
        /// assumption that costs nothing when the person is standing and is the
        /// difference between a kick and a shoe left standing in the air while
        /// the leg goes up.
        /// </summary>
        void FollowAnkle(Transform[] bones, int side)
        {
            int shin = side == 0 ? 12 : 16;
            bones[shin + 1].rotation = bones[shin].rotation * ankleBindings[side];
        }

        /// <summary>
        /// Keeps the toe at the angle the foot was modelled with.
        ///
        /// The shoe's contact patch is one rigid piece across the foot and the
        /// toe - a quarter of mizore's touching vertices are weighted to the
        /// toe - so a toe still carrying the replay clip's orientation bends
        /// the sole at the ball and lifts the front off the floor.
        /// </summary>
        void PairToe(Transform[] bones, int side)
        {
            int foot = side == 0 ? 13 : 17;
            Quaternion toe = bones[foot].rotation * toeBindings[side];
            toeFix = Mathf.Max(toeFix, Quaternion.Angle(bones[foot + 1].rotation, toe));
            bones[foot + 1].rotation = toe;
        }

        /// <summary>
        /// Aims a shoe's sole at the floor without turning the foot.
        ///
        /// A sole plane says which way is *up* for the shoe and nothing about
        /// which way the toes point: every rotation that carries that plane onto
        /// the floor is equally flat, and <see cref="Quaternion.FromToRotation"/>
        /// picks the shortest one - which takes the toes with it. Measured on the
        /// 2026-11-25 10:37 recording: the sole went from 22 degrees out to
        /// flat, and the feet came out pigeon-toed, because the 22 degrees were
        /// mostly *across* the foot, not along it.
        ///
        /// So the direction the toes had along the floor is put back afterwards,
        /// as a yaw about the world up. Yaw cannot tilt the sole again - it
        /// leaves every vector's height alone - so the sole stays flat and the
        /// foot keeps pointing where its owner pointed it.
        /// </summary>
        static float AimSole(Transform foot, Transform toe, Vector3 worldUp)
        {
            if (worldUp.sqrMagnitude < 1e-6f) return 0f;
            worldUp.Normalize();
            // A shoe this far from the floor is not standing on it. Swinging it
            // down from here turns the foot past its own side - which is how a
            // kick ends up with the shoe on its head - so the frame is left
            // alone instead.
            if (Vector3.Angle(worldUp, Vector3.up) > MaxSoleTilt) return 0f;
            Vector3 before;
            bool hadToe = ToeDirection(foot, toe, out before);
            foot.rotation = Quaternion.FromToRotation(worldUp, Vector3.up) * foot.rotation;
            // The toe moved with the foot, so its new direction is the old one
            // turned by the same rotation. Anything left over is the turn the
            // levelling introduced, and it is undone here.
            Vector3 after;
            if (!hadToe || !ToeDirection(foot, toe, out after)) return 0f;
            float undone = Vector3.Angle(after, before);
            foot.rotation = Quaternion.FromToRotation(after, before) * foot.rotation;
            return undone;
        }

        /// <summary>
        /// Where the foot points along the floor, taken from the bone that
        /// continues it rather than from a local axis: the toe bone sits at the
        /// front of the shoe, so its offset is the direction a shoe points,
        /// whichever way this particular rig was modelled.
        ///
        /// False when the toe is mostly vertical. A toe pointing at the floor
        /// has no direction along it, and the little that is left after
        /// flattening is noise - normalising it and turning the shoe to match is
        /// how a kick ends up with a shoe pointing backwards.
        /// </summary>
        static bool ToeDirection(Transform foot, Transform toe, out Vector3 flat)
        {
            flat = Vector3.zero;
            if (foot == null || toe == null) return false;
            Vector3 direction = toe.position - foot.position;
            float length = direction.magnitude;
            direction.y = 0f;
            if (length < 1e-6f || direction.magnitude < 0.5f * length) return false;
            flat = direction.normalized;
            return true;
        }

        /// <summary>The plane the actors stand on, taken from the model root.</summary>
        float FloorHeight()
        {
            return actor == null ? 0f : actor.transform.TransformPoint(Vector3.zero).y;
        }

        /// <summary>
        /// The shoe surface of the actor being driven, measured once.
        ///
        /// The loader builds one for prefab bodies; a .vrm arrives without it,
        /// and a live pose needs it more than a replay does - the legs are
        /// straightened here, which moves the shoes relative to a hip height the
        /// game picked for a different pose. Sampled in the restored bind pose,
        /// so what it keeps is the modelled shoe.
        /// </summary>
        AvatarSoleContact Soles()
        {
            if (actor == null) return null;
            if (liveSolesOwner == actor) return liveSoles;
            if (!actor.Ready) return actor.SoleContact;
            liveSolesOwner = actor;
            liveSoles = actor.SoleContact;
            if (liveSoles == null)
            {
                try { liveSoles = new AvatarSoleContact(actor.ModelRoot, actor.Bones); }
                catch (System.ArgumentException) { liveSoles = null; }
            }
            return liveSoles;
        }

        void ApplyHands()
        {
            if (actor == null) return;
            var frame = handReceiver != null && handReceiver.IsReceiving ? handReceiver.LatestFrame : null;
            if (frame == null || frame.hands == null || frame.hands.Length == 0)
            {
                handsDriving = false;
                float idle = Time.unscaledTime - lastHandApplyAt;
                // Hold through a drop-out instead of letting go on the first
                // empty frame: an empty packet means the detector blinked, not
                // that the person moved their hands. Both palettes overlapping on
                // a cross is the usual reason, and relaxing there is the
                // "disappear and come back" that was reported.
                bool holding = idle <= HandGrace;
                actor.handPoseOverridden = holding;
                actor.wristOverridden = holding;
                // Nothing has ever been driven here, so the avatar's own hand
                // pose belongs to the game: leave it alone instead of easing it
                // to a bind pose nobody asked for.
                if (holding) return;
                if (idle > HandGrace + 1f) return;
                // Given up: ease both hands back to the bind pose once, rather
                // than freezing them mid-gesture forever.
                actor.RelaxHand(true);
                actor.RelaxHand(false);
                return;
            }
            if (handPoints == null) handPoints = new Vector3[HandEntry.JointCount];
            bool left = false, right = false, measured = false;
            float palmSum = 0f;
            int palmCount = 0;
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
                    // angle. All three axes have to take that turn together.
                    //
                    // This used to be done to x and y only, with z taken from
                    // the camera frame and projected onto the plane the yawed
                    // fingers define. That mixes two frames: the plane is in
                    // the model's, the vector projected into it is in the
                    // camera's. In a side-on match the leftover is exactly the
                    // quarter turn between them, so the wrist came out twisted
                    // by 90 degrees - the palm faced the camera while the arm
                    // and the fingers pointed at the opponent ("when my palm
                    // faces the screen the puppet's palm should face the
                    // opponent, not stand perpendicular to its own body").
                    //
                    // The measured normal is the right answer once the whole
                    // frame turns with the body: palm to the camera means palm
                    // along the person's forward, and the person's forward is
                    // mapped onto the avatar's, which is the opponent. Nothing
                    // here needs to know what the yaw happens to be.
                    Quaternion toModel = liveFacing * sensorToModel;
                    hx = toModel * hx;
                    hy = toModel * hy;
                    hz = toModel * hz;
                    // Keep the frame orthonormal against float drift, and keep
                    // it right-handed the way the avatar builds its own: x is
                    // y cross z.
                    if (hy.sqrMagnitude > 1e-8f && hz.sqrMagnitude > 1e-8f)
                        hx = Vector3.Cross(hy, hz).normalized;
                    float offset = PalmOffset(hz);
                    if (offset >= 0f) { palmSum += offset; palmCount++; }
                    actor.ApplyHandSkeleton(hand.IsLeft, handPoints, hx, hy, hz);
                    if (hand.HasBasis) measured = true;
                    if (hand.IsLeft) { left = true; lastLeftHandAt = Time.unscaledTime; }
                    else { right = true; lastRightHandAt = Time.unscaledTime; }
                }
            }
            if (palmCount > 0) palmOffsetDegrees = palmSum / palmCount;
            // A hand that drops out of the packet for a frame or two has not left
            // the frame - it is behind the other arm, or the detector lost it
            // while the palms overlap. Easing it to the bind pose on that frame
            // and back onto the tracked pose on the next one is the flap that
            // reads as "it does the opposite of my hand": the crossed-arms pose
            // in the 2026-11-11 recording lost both hands for two and a half
            // seconds, and every one of those frames the receiver was posing the
            // hand from somewhere else. Hold it instead, and only give up after
            // HandGrace - the sender re-sends a solved pose for HAND_HOLD
            // (1.5 s) before a hand stops appearing at all.
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

        /// <summary>
        /// Degrees between the measured palm normal and the avatar's own facing.
        /// A hand that follows the body reads 0 (palm at the opponent) or 180
        /// (back of the hand at the opponent); 90 is the twisted wrist.
        /// </summary>
        float PalmOffset(Vector3 palmNormal)
        {
            if (modelDepth.sqrMagnitude < 0.5f || palmNormal.sqrMagnitude < 0.04f) return -1f;
            Vector3 forward = liveFacing * modelDepth;
            if (forward.sqrMagnitude < 0.5f) return -1f;
            return Vector3.Angle(palmNormal.normalized, forward.normalized);
        }

        /// <summary>
        /// Aims a shin straight down from its knee. Only for a leg whose ankle
        /// was never tracked at calibration - a tracked one is aimed at the
        /// measured ankle by the segment table, which keeps the knee angle the
        /// person actually made.
        /// </summary>
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
        /// +1 when the tracked right wrist ends up on the same side of the body
        /// as the avatar's, -1 when the two disagree, 0 when it cannot be told.
        ///
        /// A body tracker that swaps the two arms while they cross is the only
        /// thing that makes the avatar fold its arms in when the person opens
        /// them, and it is invisible in a screenshot where both arms happen to
        /// be symmetric. Projecting the wrist-to-wrist offset onto the model's
        /// own right axis makes it a single number: -1 is a swapped pair.
        /// </summary>
        int ArmOrder()
        {
            if (actor == null || receiver == null || !receiver.IsReceiving ||
                receiver.LatestFrame.bodies.Length == 0 || modelRight.sqrMagnitude < 0.5f) return 0;
            var body = receiver.LatestFrame.bodies[0];
            var leftWrist = body.Joint(JointType.LeftWrist); var rightWrist = body.Joint(JointType.RightWrist);
            if (leftWrist == null || rightWrist == null || leftWrist.status == 0 || rightWrist.status == 0) return 0;
            Vector3 sensor = MapSensorOffset(receiver.ToWorldPosition(rightWrist.position) -
                                             receiver.ToWorldPosition(leftWrist.position));
            Vector3 avatar = actor.Bones[10].position - actor.Bones[7].position;
            float measured = Vector3.Dot(sensor, modelRight), posed = Vector3.Dot(avatar, modelRight);
            // Wrists within a few centimetres of each other on that axis say
            // nothing either way - that is a cross, not a swapped pair.
            if (Mathf.Abs(measured) < 0.05f || Mathf.Abs(posed) < 0.05f) return 0;
            return (measured < 0f) == (posed < 0f) ? 1 : -1;
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
                    // sessions=2 means a second sender is on the port; withBody
                    // staying at 0 while the preview draws joints means the
                    // frames that arrive carry an empty body list.
                    "body.sessions=" + receiver.SessionsSeen + " withBody=" + receiver.FramesWithBody + "\n" +
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
                    " holdL=" + (actor != null ? actor.WristHeldFrames(true) : 0) +
                    " holdR=" + (actor != null ? actor.WristHeldFrames(false) : 0) +
                    " bendL=" + HandNumber(actor, true, false) + " bendR=" + HandNumber(actor, false, false) +
                    " handFrames=" + (handReceiver != null ? handReceiver.AcceptedFrames : 0) +
                    " palmOffset=" + (palmOffsetDegrees < 0f ? "-" : palmOffsetDegrees.ToString("F1")) +
                    " frameYaw=" + FrameYawDegrees().ToString("F1") +
                    " armDepth=" + (flipArmDepth ? "rotation" : "mirror") +
                    " armOrder=" + ArmOrder() +
                    " armPush=" + armPush.ToString("F2") +
                    " toeFix=" + toeFix.ToString("F1") +
                    " soleTilt=" + soleTilt.ToString("F1") +
                    " soleLeft=" + soleResidual.ToString("F1") +
                    " soleYaw=" + soleYaw.ToString("F1") +
                    " soleAir=" + (soleAirLeft || soleAirRight
                        ? (soleAirLeft ? "L" : "") + (soleAirRight ? "R" : "") : "-") +
                    " soleLift=" + (soleLift * 100f).ToString("F1") +
                    " legNote=" + (legNote ?? "-") + "\n" +
                    "calibNote=" + (calibrateNote ?? "-") + "\n" +
                    "status=" + status + "\n";
                File.WriteAllText(Path.GetFullPath(Path.Combine(Application.dataPath, "..", "Library", "AstraLiveStatus.txt")), text);
            }
            catch (Exception) { }
        }

        bool ShowBareStatus
        {
            get
            {
                if (game == null || !game.Ready || game.SelectionOpen || actor == null || receiver == null)
                    return false;
                if (!Calibrated) return receiver.IsReceiving;
                // A stance bind follows, but it keeps the clip's guard as the
                // neutral, so it is worth one line saying a T-pose would do
                // better.
                return stanceBound && Time.unscaledTime - calibratedAt < 10f;
            }
        }

        /// <summary>One line, top centre, only while the body is not driven.</summary>
        void DrawBindingBadge()
        {
            string text;
            float wait = bodySeenSince < 0f
                ? StanceBindDelay
                : Mathf.Max(0f, StanceBindDelay - (Time.unscaledTime - bodySeenSince));
            bool hint = Calibrated && stanceBound;
            if (hint)
                text = "Astra：已按当前站姿绑定 · 面向摄像头双臂平举 1 秒可精确校准";
            else if (receiver.LatestFrame.bodies.Length == 0)
                text = "Astra：没识别到人 · 退到 1.5–3 米，全身入镜";
            else if (wait > 0.5f)
                text = "Astra：未绑定（现在是回放动画）· 面向摄像头双臂平举 1 秒，"
                    + Mathf.CeilToInt(wait) + " 秒后按当前站姿自动绑定";
            else text = "Astra：未绑定（现在是回放动画）· 正在按当前站姿绑定…";
            if (badgeStyle == null)
            {
                badgeFont = Font.CreateDynamicFontFromOSFont("Microsoft YaHei", 14);
                badgeStyle = new GUIStyle(GUI.skin.label)
                {
                    fontSize = 14,
                    alignment = TextAnchor.MiddleCenter
                };
                if (badgeFont != null) badgeStyle.font = badgeFont;
            }
            // Bottom centre: the top of the screen is the health bars and the
            // middle is the fight. The floor band there is empty until the
            // arena logo comes up.
            var area = new Rect(0f, Screen.height - 96f, Screen.width, 22f);
            Color old = GUI.color;
            GUI.color = new Color(0f, 0f, 0f, 0.6f);
            GUI.Label(new Rect(area.x, area.y + 1f, area.width, area.height), text, badgeStyle);
            GUI.color = hint ? new Color(0.55f, 1f, 0.6f, 0.95f) : new Color(1f, 0.86f, 0.35f, 0.95f);
            GUI.Label(area, text, badgeStyle);
            GUI.color = old;
        }

        void OnGUI()
        {
            // Only ever shown while the body is not being driven. The hands work
            // without a calibration, so a session that never bound still looked
            // alive - the fingers moved - while the avatar was standing in the
            // replay clip and its shoes were the clip's. Saying it out loud is
            // the difference between "Astra is broken" and "hold your arms out".
            if (ShowBareStatus) DrawBindingBadge();
            // Off by default: this panel is 590 px wide and sits on top of the
            // fight. F1 brings it back when something needs diagnosing.
            if (!showDebugPanel) return;
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
                Calibrated ? (legNote == null ? "已校准，控制 P1"
                    : "已校准（" + legNote + "未追踪，腿部保持站立）") +
                    (Mathf.Abs(soleLift) > 0.003f
                        ? "，鞋底修正 " + (soleLift >= 0f ? "+" : "-") +
                          (Mathf.Abs(soleLift) * 100f).ToString("F1") + " cm"
                        : "（战斗回放暂停）")
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
                (handsDriving ? "　中指屈 " + HandNumber(actor, true, false) + "/" + HandNumber(actor, false, false) + "°" : "") +
                (handsDriving ? "　角色朝向差 " + FrameYawDegrees().ToString("F0") + "°" : "");
            GUI.Label(new Rect(25, 138, width - 140, 22), "手部：" + handState);
            // The answer to "is the wrist twisted". 0 = palm at the opponent,
            // 90 = edge-on (a quarter turn out), 180 = back of the hand at them
            // (press 翻转 below). A number instead of a screenshot to argue with.
            GUI.Label(new Rect(width - 105, 138, 98, 22), "掌心 " +
                (palmOffsetDegrees < 0f ? "--" : palmOffsetDegrees.ToString("F0") + "°"));
            if (GUI.Button(new Rect(width - 105, 186, 98, 18), flipPalmNormal ? "翻转：已反向" : "翻转：正常"))
            {
                flipPalmNormal = !flipPalmNormal;
                if (actor != null) actor.ResetHandRoll();
            }
            if (GUI.Button(new Rect(width - 105, 162, 98, 22), flipArmDepth ? "手臂：旋转" : "手臂：镜像"))
                flipArmDepth = !flipArmDepth;
            // These three buttons are gone on purpose: the match starts the
            // pipeline itself, and a second bridge would fight run.py's bridge
            // over the camera. This line reports what the automatic start did.
            GUI.Label(new Rect(25, 166, width - 248, 35), "摄像头：" + pipelineMessage);
            if (GUI.Button(new Rect(width - 215, 166, 110, 30), "重启摄像头"))
            {
                StopPipeline();
                StartPipeline();
            }
            string countdown = nextCalibrationAt < 0 ? "等待人体" : "下次校准 " + Mathf.CeilToInt(Mathf.Max(0, nextCalibrationAt - Time.unscaledTime)) + " 秒";
            GUI.Label(new Rect(415, 186, 158, 18), countdown);
            GUI.Label(new Rect(25, 208, width - 24, 46), "操作：选角色和场地 → 摄像头自动启动并弹出预览 → 双臂平举等待自动校准。\n手指不需要校准：只要收到 7011 报文就在驱动。身体每 5 秒尝试一次，姿势不满足时保留上次校准。");
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
            StopPipeline();
            if (uiFont != null) Destroy(uiFont);
        }

        // Exiting Play mode must not leave the bridge this panel started running:
        // an orphan bridge used to keep the UDP ports pinned after the editor was
        // gone, which made every later Play fail to bind.
        void OnDisable() { if (live == this) { StopSender(); StopPipeline(); } }

        void OnApplicationQuit() { StopSender(); StopPipeline(); }
    }
}
