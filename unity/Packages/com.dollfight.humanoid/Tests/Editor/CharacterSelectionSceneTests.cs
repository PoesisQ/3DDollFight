using System.Collections;
using NUnit.Framework;
using UniVRM10;
using UnityEngine;
using UnityEngine.SceneManagement;
using UnityEngine.TestTools;

namespace DollFight.Tests
{
    public sealed class CharacterSelectionSceneTests
    {
        [UnityTest]
        public IEnumerator PublicSelectionReloadsMirrorAndVrmSlotsWithoutLeavingPreviousActors()
        {
            yield return new EnterPlayMode();
            SceneManager.LoadScene("DollFight", LoadSceneMode.Single);
            yield return WaitForReady();
            var demo = Object.FindFirstObjectByType<DollFightDemo>();
            AssertSelectionAndFinalSnapshot(demo, "tripo-b9e9ce29", "team");

            int previous = demo.GetInstanceID();
            demo.SelectCharacters("tripo-b9e9ce29", "tripo-b9e9ce29");
            yield return WaitForReady(previous);
            demo = Object.FindFirstObjectByType<DollFightDemo>();
            AssertSelectionAndFinalSnapshot(demo, "tripo-b9e9ce29", "tripo-b9e9ce29");

            previous = demo.GetInstanceID();
            demo.SelectCharacters("mizore", "tripo-b9e9ce29");
            yield return WaitForReady(previous);
            demo = Object.FindFirstObjectByType<DollFightDemo>();
            AssertSelectionAndFinalSnapshot(demo, "mizore", "tripo-b9e9ce29");
            var previousVrm = demo.Actors[0].Instance;
            var previousVrmObject = previousVrm.gameObject;
            Assert.That(previousVrm.Runtime.SpringBone, Is.TypeOf<Vrm10FastSpringboneRuntimeStandalone>(),
                "VRM spring jobs must belong to the actor rather than a shared cross-scene service.");

            previous = demo.GetInstanceID();
            demo.SelectCharacters("tripo-b9e9ce29", "team");
            yield return WaitForReady(previous);
            demo = Object.FindFirstObjectByType<DollFightDemo>();
            AssertSelectionAndFinalSnapshot(demo, "tripo-b9e9ce29", "team");
            Assert.That(previousVrm == null, Is.True, "The previous VRM component must be destroyed on reload.");
            Assert.That(previousVrmObject == null, Is.True, "The previous imported hierarchy must be destroyed on reload.");
            Assert.That(Object.FindObjectsByType<Vrm10Instance>(FindObjectsSortMode.None).Length, Is.Zero,
                "Returning to prefab-only slots must leave no runtime VRM instance.");
            yield return new ExitPlayMode();
        }

        [UnityTearDown]
        public IEnumerator RestoreEditorModeAfterFailure()
        {
            if (Application.isPlaying) yield return new ExitPlayMode();
        }

        static IEnumerator WaitForReady(int previousInstance = 0)
        {
            float deadline = Time.realtimeSinceStartup + 120;
            DollFightDemo demo = null;
            while (Time.realtimeSinceStartup < deadline)
            {
                demo = Object.FindFirstObjectByType<DollFightDemo>();
                if (demo != null && demo.GetInstanceID() != previousInstance && demo.Ready)
                {
                    // Allow deferred destruction and the replacement actor's late update.
                    yield return null;
                    yield break;
                }
                yield return null;
            }
            Assert.Fail("Replacement scene never became ready: " + (demo == null ? "no demo" : demo.status));
        }

        static void AssertSelectionAndFinalSnapshot(DollFightDemo demo, string playerOne, string playerTwo)
        {
            Assert.That(demo.CharacterIds, Is.EqualTo(new[] { playerOne, playerTwo }));
            Assert.That(Object.FindObjectsByType<DollFightDemo>(FindObjectsSortMode.None).Length, Is.EqualTo(1));
            Assert.That(Object.FindObjectsByType<HumanoidReplay>(FindObjectsSortMode.None).Length, Is.EqualTo(2),
                "Reloaded scenes must contain exactly the two current player actors.");
            Assert.That(demo.Actors[0], Is.Not.SameAs(demo.Actors[1]), "Mirrors still require independent actors.");
            for (int player = 0; player < 2; player++)
            {
                Assert.That(demo.Actors[player].Ready, Is.True);
                bool isVrm = demo.SelectedCharacter(player).modelKind == "vrm";
                Assert.That(demo.Actors[player].Instance != null, Is.EqualTo(isVrm), "VRM selection must use the original runtime import path.");
                Assert.That(demo.Actors[player].existingHumanoid != null, Is.EqualTo(!isVrm));
                Assert.That(demo.Actors[player].gameObject.name, Does.EndWith(demo.CharacterIds[player]));
            }
            demo.playing = false;
            demo.Seek(54.7f);
            Assert.That(demo.MatchFinished, Is.True, "Changing models must retain the real KO snapshot.");
            Assert.That(demo.CurrentFrame.health, Is.EqualTo(new[] { 51f, 0f }));
            Assert.That(demo.CurrentFrame.matchState, Is.EqualTo("finished"));
        }
    }
}
