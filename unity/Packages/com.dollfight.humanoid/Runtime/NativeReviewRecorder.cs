using System;
using System.Buffers;
using System.Collections.Concurrent;
using System.Diagnostics;
using System.IO;
using System.Threading.Tasks;
using Unity.Collections;
using UnityEngine;
using UnityEngine.Rendering;

namespace DollFight
{
    // Captures the actual composed Unity frame, including all cameras and UI.
    // Rendering keeps its real-time clock; missed video samples repeat the last
    // frame instead of slowing gameplay or inventing interpolated poses.
    public sealed class NativeReviewRecorder : IDisposable
    {
        struct Frame { public int index; public byte[] pixels; }
        readonly BlockingCollection<Frame> queue = new BlockingCollection<Frame>(8);
        readonly RenderTexture[] textures = new RenderTexture[3];
        readonly bool[] occupied = new bool[3];
        readonly Process encoder;
        readonly Task writer;
        readonly int bytes;
        int lastRequested = -1, targetFrames;
        bool finishing;
        int pending;
        public bool Pending => pending > 0;
        public bool Complete => writer.IsCompleted;
        public volatile string Error;
        public int CapturedFrames { get; private set; }
        public int RepeatedFrames { get; private set; }

        public NativeReviewRecorder(string executable, string output, int width, int height)
        {
            if (!SystemInfo.supportsAsyncGPUReadback) throw new NotSupportedException("Async GPU readback required");
            if (!File.Exists(executable)) throw new FileNotFoundException("Pass an installed ffmpeg path", executable);
            output = Path.GetFullPath(output);
            Directory.CreateDirectory(Path.GetDirectoryName(output));
            bytes = checked(width * height * 4);
            for (int i = 0; i < textures.Length; i++)
            {
                textures[i] = new RenderTexture(width, height, 0, RenderTextureFormat.ARGB32);
                textures[i].Create();
            }
            string flip = SystemInfo.graphicsUVStartsAtTop ? "" : "-vf vflip";
            encoder = new Process { StartInfo = new ProcessStartInfo {
                FileName = executable,
                Arguments = $"-hide_banner -loglevel warning -nostdin -y -f rawvideo -pixel_format rgba -video_size {width}x{height} -framerate 30 -i pipe:0 -an {flip} -c:v libx264 -preset veryfast -crf 18 -pix_fmt yuv420p -movflags +faststart \"{output}\"",
                UseShellExecute = false, CreateNoWindow = true,
                RedirectStandardInput = true, RedirectStandardError = true
            }};
            encoder.Start();
            Task<string> diagnostics = encoder.StandardError.ReadToEndAsync();
            writer = Task.Run(() => WriteFrames(output, diagnostics));
        }

        // Invoke only after WaitForEndOfFrame, when the UI has also rendered.
        public void Capture(int frameIndex)
        {
            if (finishing || Error != null || frameIndex <= lastRequested) return;
            int slot = Array.FindIndex(occupied, busy => !busy);
            if (slot < 0) return;
            lastRequested = frameIndex; occupied[slot] = true; pending++;
            ScreenCapture.CaptureScreenshotIntoRenderTexture(textures[slot]);
            AsyncGPUReadback.Request(textures[slot], 0, TextureFormat.RGBA32, request => {
                occupied[slot] = false; pending--;
                if (request.hasError) { Error = "GPU frame readback failed"; return; }
                byte[] buffer = ArrayPool<byte>.Shared.Rent(bytes);
                NativeArray<byte>.Copy(request.GetData<byte>(), 0, buffer, 0, bytes);
                if (!queue.TryAdd(new Frame { index = frameIndex, pixels = buffer }))
                    ArrayPool<byte>.Shared.Return(buffer);
            });
        }

        public void Finish(int frames)
        {
            if (Pending) throw new InvalidOperationException("Wait for GPU readback before finishing");
            targetFrames = frames; finishing = true; queue.CompleteAdding();
        }

        void WriteFrames(string output, Task<string> diagnostics)
        {
            byte[] last = null;
            int written = 0;
            try
            {
                Stream stream = encoder.StandardInput.BaseStream;
                foreach (Frame frame in queue.GetConsumingEnumerable())
                {
                    if (frame.index < written) { ArrayPool<byte>.Shared.Return(frame.pixels); continue; }
                    while (written < frame.index)
                    {
                        stream.Write(last ?? frame.pixels, 0, bytes); written++; RepeatedFrames++;
                    }
                    stream.Write(frame.pixels, 0, bytes); written++; CapturedFrames++;
                    if (last != null) ArrayPool<byte>.Shared.Return(last);
                    last = frame.pixels;
                }
                if (last == null) throw new InvalidOperationException("No rendered frames received");
                while (written < targetFrames) { stream.Write(last, 0, bytes); written++; RepeatedFrames++; }
                stream.Close();
                if (!encoder.WaitForExit(30000)) throw new TimeoutException("Video encoder did not finish");
                string log = diagnostics.GetAwaiter().GetResult();
                File.WriteAllText(output + ".ffmpeg.log", log);
                if (encoder.ExitCode != 0) throw new IOException("Video encoder failed: " + log);
            }
            catch (Exception e) { Error = e.Message; }
            finally
            {
                if (last != null) ArrayPool<byte>.Shared.Return(last);
                while (queue.TryTake(out Frame frame)) ArrayPool<byte>.Shared.Return(frame.pixels);
            }
        }

        public void Dispose()
        {
            // Call after Finish/Complete. Never destroy an in-flight GPU target.
            if (!Complete || Pending) throw new InvalidOperationException("Recording is still active");
            foreach (var texture in textures) { texture.Release(); UnityEngine.Object.Destroy(texture); }
            encoder.Dispose(); queue.Dispose();
        }
    }
}
