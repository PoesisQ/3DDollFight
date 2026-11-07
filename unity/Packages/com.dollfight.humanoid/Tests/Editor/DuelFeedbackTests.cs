using System;
using System.Collections;
using System.Reflection;
using NUnit.Framework;
using UnityEngine;

namespace DollFight.Tests
{
    public sealed class DuelFeedbackTests
    {
        GameObject root;
        DuelFeedback feedback;
        double now;

        [SetUp]
        public void SetUp()
        {
            root = new GameObject("feedback boundary test");
            feedback = root.AddComponent<DuelFeedback>();
            feedback.soundEnabled = feedback.hapticsEnabled = false;
            now = 10;
            SetField("clock", (Func<double>)(() => now));
        }

        [TearDown]
        public void TearDown() { UnityEngine.Object.DestroyImmediate(root); }

        [Test]
        public void DroppedFrameConsumesBothDirectionsAndOverlappingWindowsDoNotDuplicate()
        {
            var contacts = new[] {
                Contact("later", 0.24f, 1), Contact("first", 0.2f, 0), Contact("miss", 0.23f, 0, "miss")
            };
            feedback.ResetAt(0, contacts);
            feedback.Advance(0.1f, 0.3f, contacts, true);
            Assert.AreEqual(2, PulseCount);
            Assert.AreEqual("later", feedback.LastContact.id);
            feedback.Advance(0.1f, 0.3f, contacts, true);
            feedback.Advance(0.3f, 0.4f, contacts, true);
            Assert.AreEqual(2, PulseCount, "A replayed/overlapping interval must not create another impulse.");
        }

        [Test]
        public void ShortSeekClearsFeedbackAndReplaysOnlyContactsAfterItsDestination()
        {
            var contacts = new[] { Contact("first", 0.2f), Contact("later", 0.24f) };
            feedback.Advance(0, 0.3f, contacts, true);
            feedback.ResetAt(0.21f, contacts);
            Assert.AreEqual(0, PulseCount);
            Assert.IsNull(feedback.LastContact);
            Assert.IsTrue(float.IsPositiveInfinity(feedback.ContactAge));
            feedback.Advance(0.21f, 0.3f, contacts, true);
            Assert.AreEqual(1, PulseCount);
            Assert.AreEqual("later", feedback.LastContact.id);
            feedback.ResetAt(0, contacts);
            feedback.Advance(0, 0.21f, contacts, true);
            Assert.AreEqual("first", feedback.LastContact.id, "Seeking backwards starts a fresh consumption history.");
        }

        [Test]
        public void PauseClearsHitstopAndDoesNotQueueContactsForResume()
        {
            var contacts = new[] { Contact("first", 0.2f), Contact("paused", 0.24f), Contact("resumed", 0.4f) };
            feedback.Advance(0, 0.21f, contacts, true);
            Assert.AreEqual(0, feedback.PlaybackDelta(0.01f));
            feedback.Advance(0.21f, 0.3f, contacts, false);
            Assert.AreEqual(0, PulseCount);
            Assert.IsNull(feedback.LastContact);
            Assert.AreEqual(0.01f, feedback.PlaybackDelta(0.01f), 1e-6f);
            feedback.Advance(0.2f, 0.3f, contacts, true);
            Assert.AreEqual(0, PulseCount);
            feedback.Advance(0.3f, 0.41f, contacts, true);
            Assert.AreEqual("resumed", feedback.LastContact.id);
        }

        [Test]
        public void HitstopUsesRealTimeAndPreservesTheUnfrozenPartOfALongFrame()
        {
            float originalTimeScale = Time.timeScale;
            var contacts = new[] { Contact("light", 0.2f) };
            feedback.Advance(0, 0.21f, contacts, true); // light impact freezes 45 ms
            Assert.AreEqual(0, feedback.PlaybackDelta(0.1f));
            now += 0.1;
            Assert.AreEqual(0.11f, feedback.PlaybackDelta(0.2f), 1e-5f,
                "A 100 ms real frame with 45 ms of hitstop retains 55% of its playback step.");
            now += 0.1;
            Assert.AreEqual(0.2f, feedback.PlaybackDelta(0.2f), 1e-6f);
            Assert.AreEqual(originalTimeScale, Time.timeScale);
        }

        [Test]
        public void FocusLossClearsResidualEffectsAndFreezesPlaybackUntilFocusReturns()
        {
            var contacts = new[] { Contact("first", 0.2f) };
            feedback.Advance(0, 0.21f, contacts, true);
            Invoke("OnApplicationFocus", false);
            Assert.IsNull(feedback.LastContact);
            Assert.AreEqual(0, PulseCount);
            Assert.AreEqual(0, feedback.PlaybackDelta(0.1f));
            Invoke("OnApplicationFocus", true);
            now += 0.1;
            Assert.AreEqual(0.1f, feedback.PlaybackDelta(0.1f), 1e-6f);
        }

        [Test]
        public void UnattendedReviewKeepsConsumingContactsAndAdvancingWhileUnfocused()
        {
            // Use reflection so this test compiles before the diagnostic option exists.
            var option = typeof(DuelFeedback).GetField("ignoreApplicationFocus");
            Assert.That(option, Is.Not.Null);
            option.SetValue(feedback, true);
            var contacts = new[] { Contact("first", .2f), Contact("final", .4f) };
            feedback.Advance(0, .21f, contacts, true);
            Invoke("OnApplicationFocus", false);
            Assert.That(feedback.LastContact.id, Is.EqualTo("first"));
            now += .1;
            Assert.That(feedback.PlaybackDelta(.1f), Is.EqualTo(.1f).Within(1e-6f));
            feedback.Advance(.21f, .41f, contacts, true);
            Assert.That(feedback.LastContact.id, Is.EqualTo("final"));
            Assert.That(PulseCount, Is.EqualTo(2));
        }

        [Test]
        public void RestoreCameraPreservesExternalTranslationAndWorldRotation()
        {
            var cameraObject = new GameObject("camera boundary test");
            try
            {
                var camera = cameraObject.AddComponent<Camera>();
                Vector3 origin = new Vector3(3, 2, 5);
                Quaternion rotation = Quaternion.Euler(12, 145, 0);
                camera.transform.SetPositionAndRotation(origin, rotation);
                feedback.Advance(0, 0.21f, new[] { Contact("shake", 0.2f) }, true);
                feedback.ApplyCamera(camera);
                Vector3 externalMove = new Vector3(0.5f, 0.2f, -0.3f);
                Quaternion externalTurn = Quaternion.Euler(3, 8, -2);
                camera.transform.position += externalMove;
                camera.transform.rotation = externalTurn * camera.transform.rotation;
                feedback.RestoreCamera(camera);
                Assert.Less(Vector3.Distance(origin + externalMove, camera.transform.position), 1e-5f);
                Assert.Less(Quaternion.Angle(externalTurn * rotation, camera.transform.rotation), 0.01f);
                Vector3 restored = camera.transform.position;
                feedback.RestoreCamera(camera);
                Assert.AreEqual(restored, camera.transform.position, "Restoration must be idempotent.");
            }
            finally { UnityEngine.Object.DestroyImmediate(cameraObject); }
        }

        [Test]
        public void SameTimestampContactsRemainSeparateAndAnExactSeekDoesNotReplayThem()
        {
            var contacts = new[] { Contact("a", 0.2f, 0), Contact("b", 0.2f, 1) };
            feedback.Advance(0, 0.2f, contacts, true);
            Assert.AreEqual(2, PulseCount);
            feedback.ResetAt(0.2f, contacts);
            feedback.Advance(0.19f, 0.21f, contacts, true);
            Assert.AreEqual(0, PulseCount);
        }

        [Test]
        public void ProceduralClipsHaveNoClippedSamplesOrMaterialDcOffset()
        {
            var make = typeof(DuelFeedback).GetMethod("MakeClip", BindingFlags.Static | BindingFlags.NonPublic);
            for (int kind = 0; kind < 5; kind++)
            {
                var clip = (AudioClip)make.Invoke(null, new object[] { kind });
                try
                {
                    var samples = new float[clip.samples];
                    Assert.IsTrue(clip.GetData(samples, 0));
                    double sum = 0;
                    float peak = 0;
                    foreach (float sample in samples)
                    {
                        Assert.IsTrue(float.IsFinite(sample));
                        sum += sample;
                        peak = Mathf.Max(peak, Mathf.Abs(sample));
                    }
                    Assert.Less(peak, 0.95f, clip.name + " unexpectedly reaches the hard limiter.");
                    Assert.Less(Math.Abs(sum / samples.Length), 0.003, clip.name + " has material DC offset.");
                    Assert.AreEqual(0, samples[0]);
                }
                finally { UnityEngine.Object.DestroyImmediate(clip); }
            }
        }

        [Test]
        public void SimultaneousSoundsReserveSeparateVoicesBeforeDspStarts()
        {
            typeof(DuelFeedback).GetMethod("CreateAudio", BindingFlags.Instance | BindingFlags.NonPublic).Invoke(feedback, null);
            var clips = (AudioClip[])GetField("clips");
            var reserve = typeof(DuelFeedback).GetMethod("ReserveVoice", BindingFlags.Instance | BindingFlags.NonPublic);
            int first = (int)reserve.Invoke(feedback, new object[] { clips[0], 1f, now });
            int second = (int)reserve.Invoke(feedback, new object[] { clips[1], 1f, now });
            Assert.AreNotEqual(first, second, "A same-frame second hit must not restart the first sound.");
            feedback.ResetAt(0, null);
            int reset = (int)reserve.Invoke(feedback, new object[] { clips[0], 1f, now });
            Assert.AreEqual(first, reset, "Seeking releases all voice reservations.");
        }

        [Test]
        public void DestroyReleasesSynthesizedClipsButPreservesBorrowedSamples()
        {
            typeof(DuelFeedback).GetMethod("CreateAudio", BindingFlags.Instance | BindingFlags.NonPublic).Invoke(feedback, null);
            var owned = (AudioClip[])GetField("clips");
            var borrowed = AudioClip.Create("borrowed sample ownership test", 128, 1, 44100, false);
            try
            {
                SetField("sampledClips", new[] { borrowed });
                foreach (var clip in owned) Assert.IsTrue(clip != null, "The test must begin with live generated clips.");
                // This non-ExecuteAlways component never enters the play lifecycle in
                // EditMode. Invoke its teardown just as CreateAudio was invoked above;
                // DestroyImmediate alone does not deliver that runtime callback here.
                typeof(DuelFeedback).GetMethod("OnDestroy", BindingFlags.Instance | BindingFlags.NonPublic).Invoke(feedback, null);
                UnityEngine.Object.DestroyImmediate(root);
                root = null;
                foreach (var clip in owned) Assert.IsTrue(clip == null, "Generated clips must be released with feedback.");
                Assert.IsTrue(borrowed != null, "Resources-loaded samples may be shared and must survive feedback teardown.");
            }
            finally
            {
                foreach (var clip in owned) if (clip != null) UnityEngine.Object.DestroyImmediate(clip);
                UnityEngine.Object.DestroyImmediate(borrowed);
            }
        }

        int PulseCount => ((ICollection)GetField("pulses")).Count;
        object GetField(string name) => typeof(DuelFeedback).GetField(name, BindingFlags.Instance | BindingFlags.NonPublic).GetValue(feedback);
        void SetField(string name, object value) => typeof(DuelFeedback).GetField(name, BindingFlags.Instance | BindingFlags.NonPublic).SetValue(feedback, value);
        void Invoke(string name, object value) => typeof(DuelFeedback).GetMethod(name, BindingFlags.Instance | BindingFlags.NonPublic).Invoke(feedback, new[] { value });
        static DuelContact Contact(string id, float time, int attacker = 0, string outcome = "hit") => new DuelContact {
            id = id, time = time, attacker = attacker, defender = 1 - attacker,
            outcome = outcome, action = "jab", damage = 8, position = new Vector3(0, 1, 0)
        };
    }
}
