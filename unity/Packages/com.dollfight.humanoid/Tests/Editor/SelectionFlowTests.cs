using System;
using System.Linq;
using System.Reflection;
using NUnit.Framework;
using UnityEngine;

namespace DollFight.Tests
{
    public sealed class SelectionFlowTests
    {
        [Test]
        public void StageCatalogMapsThreeDistinctNativeScenesAndRejectsUnknownIds()
        {
            Assert.That(StageCatalog.All.Select(stage => stage.id), Is.EqualTo(new[] { "underground", "saint-maurice", "cloud" }));
            Assert.That(StageCatalog.All.Select(stage => stage.sceneName), Is.EqualTo(new[] { "DollFight", "SaintMauriceDuel", "CloudDuel" }));
            Assert.That(StageCatalog.All.Select(stage => stage.previewResource).Distinct().Count(), Is.EqualTo(3));
            Assert.Throws<ArgumentException>(() => StageCatalog.Get("unknown"));
            Assert.Throws<ArgumentException>(() => StageCatalog.Get(null));
        }

        [TestCase("unknown", "team", "cloud")]
        [TestCase("mizore", "unknown", "cloud")]
        [TestCase("mizore", "nozomi", "unknown")]
        public void InvalidMatchChoiceCannotPartiallyCommitCharactersOrStage(string first, string second, string stage)
        {
            var owner = new GameObject("selection validation");
            try
            {
                var demo = owner.AddComponent<DollFightDemo>(); demo.enabled = false;
                var catalog = CharacterCatalog.Load();
                Set(demo, "<Catalog>k__BackingField", catalog);
                Set(demo, "selection", CharacterSelection.FromArguments(catalog, Array.Empty<string>()));
                var initial = demo.CharacterIds;
                string initialStage = demo.SelectedStageId;
                Assert.Throws<ArgumentException>(() => demo.StartMatch(first, second, stage));
                Assert.That(demo.CharacterIds, Is.EqualTo(initial));
                Assert.That(demo.SelectedStageId, Is.EqualTo(initialStage));
            }
            finally { UnityEngine.Object.DestroyImmediate(owner); }
        }

        [TestCase("-dollfightSkipSelection")]
        [TestCase("-dollfightStage")]
        [TestCase("-dollfightStagePreview")]
        [TestCase("-dollfightGeometryAudit")]
        [TestCase("-dollfightPresentationReview")]
        [TestCase("-runTests")]
        public void DeveloperEntrypointsKeepDirectPlayback(string option) =>
            Assert.That(DollFightDemo.BypassSelection(new[] { "DollFight.exe", option, "value" }), Is.True);

        [Test]
        public void NormalLaunchAndSelectionReviewStartAtTheSelectionScreen()
        {
            Assert.That(DollFightDemo.BypassSelection(Array.Empty<string>()), Is.False);
            Assert.That(DollFightDemo.BypassSelection(new[] { "-dollfightSelectionReview", "folder" }), Is.False);
        }

        static void Set(DollFightDemo demo, string field, object value) =>
            typeof(DollFightDemo).GetField(field, BindingFlags.Instance | BindingFlags.NonPublic).SetValue(demo, value);
    }
}
