using System;
using System.Diagnostics;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Threading;
using UnityEngine;

namespace AstraUnity
{
    [DefaultExecutionOrder(-100)]
    public sealed class AstraSkeletonReceiver : MonoBehaviour
    {
        [Tooltip("Default: this computer only. Use 0.0.0.0 for a sender on another computer.")]
        public string listenAddress = "127.0.0.1";
        public int port = 7001;
        [Min(0.1f)] public float timeoutSeconds = 1f;
        [Tooltip("Signs of the Astra axes. Change only after checking with the real camera.")]
        public Vector3 axisSigns = Vector3.one;
        public bool mirrorX;

        public SkeletonFrame LatestFrame { get; private set; }
        public long AcceptedFrames { get; private set; }
        public string LastError { get; private set; }
        // Zero means that no person is currently selected.
        public int SelectedBodyId { get; private set; }
        public bool IsReceiving { get { return LatestFrame != null && AgeSeconds <= timeoutSeconds; } }
        /// <summary>True when the UDP socket is actually open (not just "no frames yet").</summary>
        public bool IsListening { get { return client != null; } }
        public double AgeSeconds { get { return (Stopwatch.GetTimestamp() - lastAcceptedTicks) / (double)Stopwatch.Frequency; } }
        public event Action<SkeletonFrame> FrameReceived;

        private sealed class Datagram
        {
            public string json;
            public long ticks;
        }
        private readonly object gate = new object();
        private Datagram pending;
        private string workerError;
        private long lastAcceptedTicks;
        private UdpClient client;
        private Thread worker;
        private volatile bool running;
        // A duplicate instance would bind the same UDP port and take the frames
        // away from the live one, so only the first enabled receiver listens.
        private static AstraSkeletonReceiver bound;
        private float nextBindAttempt;

        [System.Runtime.InteropServices.DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool SetHandleInformation(IntPtr handle, uint mask, uint flags);

        /// <summary>
        /// Winsock handles are created inheritable, so any child process started by
        /// Unity (for example the bridge launched from the panel) keeps the port
        /// bound after the editor exits — a "ghost" that blocks every later Play
        /// even though the owning process is gone. Clear the inherit flag.
        /// </summary>
        private static void MakeNonInheritable(UdpClient socket)
        {
            try { SetHandleInformation(socket.Client.Handle, 1u, 0u); }
            catch (Exception) { }
        }

        private void OnEnable()
        {
            if (bound != null && bound != this)
            {
                running = false;
                LastError = "另一个 Astra 数据接收器已占用 UDP " + port + "，本实例已停用。";
                enabled = false;
                return;
            }
            bound = this;
            LatestFrame = null; AcceptedFrames = 0; LastError = null; lastAcceptedTicks = 0; SelectedBodyId = 0;
            lock (gate) { pending = null; workerError = null; }
            TryBind(true);
        }

        /// <summary>
        /// Opens the listening socket. A failure used to be permanent, so a socket
        /// left behind by an earlier Play session in the same editor process kept
        /// the panel dead until Unity itself restarted. Now Update retries every
        /// two seconds and the panel offers a manual reconnect.
        /// </summary>
        public bool TryBind(bool verbose)
        {
            if (client != null) return true;
            try
            {
                if (port < 1 || port > 65535) throw new ArgumentException("UDP port must be 1..65535");
                var address = IPAddress.Parse(listenAddress);
                if (address.AddressFamily != AddressFamily.InterNetwork) throw new ArgumentException("Use an IPv4 listen address");
                var opened = new UdpClient(new IPEndPoint(address, port));
                opened.Client.ReceiveTimeout = 200;
                opened.Client.ReceiveBufferSize = 262144;
                MakeNonInheritable(opened);
                client = opened;
                running = true;
                var socket = opened;
                worker = new Thread(() => ReceiveLoop(socket)) { IsBackground = true, Name = "Astra UDP receiver" };
                worker.Start();
                LastError = null;
                nextBindAttempt = 0f;
                if (verbose) UnityEngine.Debug.Log("已监听身体 UDP " + port, this);
                return true;
            }
            catch (Exception e)
            {
                running = false;
                if (client != null) { try { client.Close(); } catch (Exception) { } client = null; }
                LastError = "无法监听 UDP " + port + "：端口被占用（" + e.Message + "）。点面板「重连」；仍失败就彻底退出 Unity 再重开。";
                if (verbose) UnityEngine.Debug.LogError(LastError, this);
                nextBindAttempt = Time.unscaledTime + 2f;
                return false;
            }
        }

        /// <summary>Closes the socket without touching the enabled state.</summary>
        private void CloseSocket()
        {
            running = false;
            if (client != null) { try { client.Close(); } catch (Exception) { } client = null; }
            if (worker != null) { try { worker.Join(500); } catch (Exception) { } worker = null; }
        }

        /// <summary>Drops the current socket and binds again (panel button).</summary>
        public void Reconnect()
        {
            CloseSocket();
            if (bound == null || bound == this) bound = this;
            nextBindAttempt = 0f;
            if (enabled) TryBind(true);
        }

        private void ReceiveLoop(UdpClient socket)
        {
            var sender = new IPEndPoint(IPAddress.Any, 0);
            while (running)
            {
                try
                {
                    byte[] bytes = socket.Receive(ref sender);
                    if (bytes.Length == 0 || bytes.Length > 60000) continue;
                    var message = new Datagram { json = Encoding.UTF8.GetString(bytes), ticks = Stopwatch.GetTimestamp() };
                    lock (gate) pending = message;
                }
                catch (SocketException e)
                {
                    if (!running) break;
                    if (e.SocketErrorCode == SocketError.TimedOut || e.SocketErrorCode == SocketError.WouldBlock) continue;
                    lock (gate) workerError = "UDP receive failed: " + e.Message;
                    break;
                }
                catch (ObjectDisposedException) { break; }
            }
        }

        private void Update()
        {
            if (client == null && Time.unscaledTime >= nextBindAttempt) TryBind(false);
            Datagram message; string error;
            lock (gate) { message = pending; pending = null; error = workerError; workerError = null; }
            if (error != null) { LastError = error; UnityEngine.Debug.LogError(error, this); }
            if (message == null) return;
            try
            {
                // Keep parsing, event callbacks and all Unity objects on the main thread.
                var frame = JsonUtility.FromJson<SkeletonFrame>(message.json);
                if (frame == null || !frame.IsValid()) return;
                // Ignore duplicate/out-of-order frames; allow restart after the old sender times out.
                if (LatestFrame != null && IsReceiving &&
                    (frame.session != LatestFrame.session || frame.sequence <= LatestFrame.sequence)) return;
                if (LatestFrame == null || frame.session != LatestFrame.session) SelectedBodyId = 0;
                SelectOneBody(frame);
                LatestFrame = frame; lastAcceptedTicks = message.ticks; ++AcceptedFrames; LastError = null;
            }
            catch (ArgumentException) { return; }
            if (FrameReceived != null) FrameReceived(LatestFrame);
        }

        private void SelectOneBody(SkeletonFrame frame)
        {
            SkeletonBody selected = null;
            foreach (var body in frame.bodies)
                if (body.IsTracked && body.id == SelectedBodyId) { selected = body; break; }

            // Select deterministically only when the previous person is no longer tracked.
            if (selected == null)
                foreach (var body in frame.bodies)
                    if (body.IsTracked && (selected == null || body.id < selected.id)) selected = body;

            SelectedBodyId = selected == null ? 0 : selected.id;
            frame.bodies = selected == null ? Array.Empty<SkeletonBody>() : new[] { selected };
        }

        public Vector3 ToLocalPosition(Vector3 millimeters)
        {
            var p = Vector3.Scale(millimeters * 0.001f, axisSigns);
            if (mirrorX) p.x = -p.x;
            return p;
        }

        /// <summary>
        /// Same axis convention as <see cref="ToLocalPosition"/>, without the
        /// millimetre-to-metre scaling: use it for normals and directions.
        /// </summary>
        public Vector3 ToLocalDirection(Vector3 unit)
        {
            var d = Vector3.Scale(unit, axisSigns);
            if (mirrorX) d.x = -d.x;
            return d;
        }

        public Vector3 ToWorldPosition(Vector3 millimeters) { return transform.TransformPoint(ToLocalPosition(millimeters)); }

        private void OnDisable()
        {
            if (bound == this) bound = null;
            CloseSocket();
            LatestFrame = null; SelectedBodyId = 0;
            lock (gate) pending = null;
        }

        private void OnApplicationQuit() { CloseSocket(); }
    }
}
