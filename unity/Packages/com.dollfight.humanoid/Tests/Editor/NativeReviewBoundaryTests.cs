using System;
using System.Collections;
using System.IO;
using System.Reflection;
using NUnit.Framework;
using UnityEngine;

namespace DollFight.Tests
{
    public sealed class NativeReviewBoundaryTests
    {
        [Test]
        public void RecordingWithinOneMillisecondOfKnockoutKeepsWaitingForTheActualFinalSnapshot()
        {
            string folder = Path.Combine(Path.GetTempPath(), "DollFight-review-" + Guid.NewGuid().ToString("N"));
            var owner = new GameObject("native recording boundary");
            IEnumerator recording = null;
            try
            {
                Directory.CreateDirectory(folder);
                File.WriteAllText(Path.Combine(folder, "start.txt"), "test start");
                var demo = owner.AddComponent<DollFightDemo>();
                demo.enabled = false;
                var feedback = owner.AddComponent<DuelFeedback>();
                feedback.soundEnabled = feedback.hapticsEnabled = false;
                Set(demo, "<Feedback>k__BackingField", feedback);
                Set(demo, "<Ready>k__BackingField", true);
                Set(demo, "selection", CharacterSelection.FromArguments(CharacterCatalog.Load(), Array.Empty<string>()));
                var timeline = JsonUtility.FromJson<DuelTimeline>(
                    "{\"matchMode\":\"knockout\",\"finishTime\":54.7,\"duration\":55,\"frames\":[" +
                    "{\"time\":0,\"matchState\":\"active\",\"health\":[51,6]}," +
                    "{\"time\":54.7,\"matchState\":\"finished\",\"health\":[51,0]}]}");
                Set(demo, "timeline", timeline);
                // Startup warmup is rendered by Unity; this EditMode regression
                // drives the actual recorder coroutine around its finish boundary.
                var clockReady = typeof(DollFightDemo).GetField("playbackClockReady", BindingFlags.Instance | BindingFlags.NonPublic);
                clockReady?.SetValue(demo, true);
                recording = (IEnumerator)typeof(DollFightDemo).GetMethod("RecordReview", BindingFlags.Instance | BindingFlags.NonPublic)
                    .Invoke(demo, new object[] { folder });
                demo.playing = false;
                int steps = 0;
                while (!demo.playing && steps++ < 20) Assert.That(recording.MoveNext(), Is.True);
                Assert.That(demo.playing, Is.True, "Recording must have reached its playback loop.");
                demo.time = timeline.finishTime - .001f;
                Assert.That(demo.MatchFinished, Is.False);
                Assert.That(recording.MoveNext(), Is.True, "A pre-KO frame cannot complete the recording.");
                Assert.That(demo.playing, Is.True);
                Assert.That(File.Exists(Path.Combine(folder, "complete.json")), Is.False);
                demo.time = timeline.finishTime;
                Assert.That(demo.MatchFinished, Is.True);
                Assert.That(recording.MoveNext(), Is.True, "The actual KO now enters the result hold.");
                Assert.That(demo.playing, Is.False);
            }
            finally
            {
                (recording as IDisposable)?.Dispose();
                UnityEngine.Object.DestroyImmediate(owner);
                if (Directory.Exists(folder)) Directory.Delete(folder, true);
            }
        }

        static void Set(DollFightDemo demo, string field, object value) =>
            typeof(DollFightDemo).GetField(field, BindingFlags.Instance | BindingFlags.NonPublic).SetValue(demo, value);
    }
}
