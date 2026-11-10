using System;
using System.Diagnostics;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Threading;
using UnityEngine;

namespace AstraUnity
{
    /// <summary>
    /// Receives ``dollfight-hands-*`` datagrams from the Python hand tracker.
    /// Versions 1 to 3 are accepted; only 3 carries the wrist rotation.
    /// Mirrors AstraSkeletonReceiver's single-slot, main-thread-parsing model so
    /// no Unity API is touched from the socket thread.
    /// </summary>
    public sealed class AstraHandReceiver : MonoBehaviour
    {
        public string listenAddress = "127.0.0.1";
        public int port = 7011;
        [Min(0.1f)] public float timeoutSeconds = 0.6f;

        public HandFrame LatestFrame { get; private set; }
        public long AcceptedFrames { get; private set; }
        public string LastError { get; private set; }
        public bool IsReceiving { get { return LatestFrame != null && AgeSeconds <= timeoutSeconds; } }
        /// <summary>True when the UDP socket is actually open (not just "no frames yet").</summary>
        public bool IsListening { get { return client != null; } }
        public double AgeSeconds { get { return (Stopwatch.GetTimestamp() - lastAcceptedTicks) / (double)Stopwatch.Frequency; } }
        public event Action<HandFrame> FrameReceived;

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
        // Same guard as AstraSkeletonReceiver: a duplicate would steal the hand
        // frames from the receiver that is actually driving the avatar.
        private static AstraHandReceiver bound;
        private float nextBindAttempt;

        [System.Runtime.InteropServices.DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool SetHandleInformation(IntPtr handle, uint mask, uint flags);

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
                LastError = "另一个手部接收器已占用 UDP " + port + "，本实例已停用。";
                enabled = false;
                return;
            }
            bound = this;
            LatestFrame = null; AcceptedFrames = 0; LastError = null; lastAcceptedTicks = 0;
            lock (gate) { pending = null; workerError = null; }
            TryBind(true);
        }

        /// <summary>Same retry policy as AstraSkeletonReceiver: never fail for good.</summary>
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
                opened.Client.ReceiveBufferSize = 65536;
                MakeNonInheritable(opened);
                client = opened;
                running = true;
                var socket = opened;
                worker = new Thread(() => ReceiveLoop(socket)) { IsBackground = true, Name = "Hand UDP receiver" };
                worker.Start();
                LastError = null;
                nextBindAttempt = 0f;
                if (verbose) UnityEngine.Debug.Log("已监听手部 UDP " + port, this);
                return true;
            }
            catch (Exception e)
            {
                running = false;
                if (client != null) { try { client.Close(); } catch (Exception) { } client = null; }
                LastError = "无法监听手部 UDP " + port + "：端口被占用（" + e.Message + "）。点面板「重连」；仍失败就彻底退出 Unity 再重开。";
                if (verbose) UnityEngine.Debug.LogError(LastError, this);
                nextBindAttempt = Time.unscaledTime + 2f;
                return false;
            }
        }

        private void CloseSocket()
        {
            running = false;
            if (client != null) { try { client.Close(); } catch (Exception) { } client = null; }
            if (worker != null) { try { worker.Join(500); } catch (Exception) { } worker = null; }
        }

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
                    lock (gate) workerError = "Hand UDP receive failed: " + e.Message;
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
                var frame = JsonUtility.FromJson<HandFrame>(message.json);
                if (frame == null || !frame.IsValid()) return;
                if (LatestFrame != null && IsReceiving &&
                    (frame.session != LatestFrame.session || frame.sequence <= LatestFrame.sequence)) return;
                LatestFrame = frame; lastAcceptedTicks = message.ticks; ++AcceptedFrames; LastError = null;
            }
            catch (ArgumentException) { return; }
            if (FrameReceived != null) FrameReceived(LatestFrame);
        }

        private void OnDisable()
        {
            if (bound == this) bound = null;
            CloseSocket();
            LatestFrame = null;
            lock (gate) pending = null;
        }

        private void OnApplicationQuit() { CloseSocket(); }
    }
}
