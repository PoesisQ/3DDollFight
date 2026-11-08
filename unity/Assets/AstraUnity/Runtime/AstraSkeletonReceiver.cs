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

        private void OnEnable()
        {
            LatestFrame = null; AcceptedFrames = 0; LastError = null; lastAcceptedTicks = 0; SelectedBodyId = 0;
            lock (gate) { pending = null; workerError = null; }
            try
            {
                if (port < 1 || port > 65535) throw new ArgumentException("UDP port must be 1..65535");
                var address = IPAddress.Parse(listenAddress);
                if (address.AddressFamily != AddressFamily.InterNetwork) throw new ArgumentException("Use an IPv4 listen address");
                client = new UdpClient(new IPEndPoint(address, port));
                client.Client.ReceiveTimeout = 200;
                client.Client.ReceiveBufferSize = 262144;
                running = true;
                var socket = client;
                worker = new Thread(() => ReceiveLoop(socket)) { IsBackground = true, Name = "Astra UDP receiver" };
                worker.Start();
            }
            catch (Exception e)
            {
                running = false; if (client != null) client.Close(); client = null;
                LastError = "Cannot listen for Astra data: " + e.Message;
                UnityEngine.Debug.LogError(LastError, this);
            }
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

        public Vector3 ToWorldPosition(Vector3 millimeters) { return transform.TransformPoint(ToLocalPosition(millimeters)); }

        private void OnDisable()
        {
            running = false;
            if (client != null) client.Close();
            if (worker != null) worker.Join(1000);
            worker = null; client = null; LatestFrame = null; SelectedBodyId = 0;
            lock (gate) pending = null;
        }
    }
}
