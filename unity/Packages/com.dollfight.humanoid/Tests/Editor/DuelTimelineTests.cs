using NUnit.Framework;
using UnityEngine;

namespace DollFight.Tests
{
    public sealed class DuelTimelineTests
    {
        [Test]
        public void MissingPresentationMetadataKeepsLegacyClock()
        {
            var timeline = JsonUtility.FromJson<DuelTimeline>("{\"duration\":135}");
            Assert.That(timeline.EffectivePresentationRate, Is.EqualTo(.75f));
        }

        [TestCase(0f)]
        [TestCase(-1f)]
        [TestCase(float.NaN)]
        [TestCase(float.PositiveInfinity)]
        public void InvalidPresentationRateFallsBackToLegacyClock(float rate)
        {
            Assert.That(new DuelTimeline { presentationRate = rate }.EffectivePresentationRate, Is.EqualTo(.75f));
        }

        [Test]
        public void ShowcaseClockReadsExplicitMetadata()
        {
            var timeline = JsonUtility.FromJson<DuelTimeline>("{\"presentationRate\":1.2,\"presentationProfile\":\"showcase\",\"regulationDuration\":66}");
            Assert.That(timeline.EffectivePresentationRate, Is.EqualTo(1.2f));
            Assert.That(timeline.regulationDuration / timeline.EffectivePresentationRate, Is.EqualTo(55).Within(.0001f));
            Assert.That(timeline.presentationProfile, Is.EqualTo("showcase"));
        }

        [Test]
        public void JsonRoundtripFindsFirstKnockoutSnapshotAtItsExactTime()
        {
            var timeline = JsonUtility.FromJson<DuelTimeline>(
                "{\"fps\":30,\"finishTime\":84.1333,\"frames\":[" +
                "{\"time\":84.1,\"health\":[100,8],\"matchState\":\"active\"}," +
                "{\"time\":84.1333,\"health\":[100,0],\"matchState\":\"finished\"}]}");
            Assert.That(timeline.FrameAt(timeline.finishTime).matchState, Is.EqualTo("finished"));
            Assert.That(timeline.FrameAt(timeline.finishTime).health[1], Is.Zero);
            Assert.That(timeline.FrameAt(timeline.finishTime - .001f).health[1], Is.EqualTo(8));
            Assert.That(timeline.FrameAt(timeline.finishTime + 1).health[1], Is.Zero);
        }

        [Test]
        public void SnapshotLookupUsesActualTimesWhenNominalRateDoesNotDivideTheTime()
        {
            var timeline = new DuelTimeline { fps = 30, frames = new[] {
                new DuelFrame { time = 0 }, new DuelFrame { time = .1333f }, new DuelFrame { time = .2667f }
            } };
            Assert.That(timeline.FrameAt(.1332f), Is.SameAs(timeline.frames[0]));
            Assert.That(timeline.FrameAt(.1333f), Is.SameAs(timeline.frames[1]));
            Assert.That(timeline.FrameAt(.2666f), Is.SameAs(timeline.frames[1]));
        }
    }
}
