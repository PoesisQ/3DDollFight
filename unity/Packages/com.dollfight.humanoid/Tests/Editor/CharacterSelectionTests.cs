using System;
using System.IO;
using System.Reflection;
using NUnit.Framework;
using UnityEngine;

namespace DollFight.Tests
{
    public sealed class CharacterSelectionTests
    {
        CharacterCatalog catalog;
        [SetUp] public void SetUp() { ResetSession(); catalog = CharacterCatalog.Load(); }
        [TearDown] public void TearDown() { ResetSession(); }
        static void ResetSession() => typeof(CharacterSelection).GetMethod("ResetSession", BindingFlags.Static | BindingFlags.NonPublic).Invoke(null, null);

        [Test] public void DirectoryKeepsAllFourCharactersAndUsesStableIds()
        {
            Assert.That(catalog.Characters.Count, Is.EqualTo(4));
            Assert.That(catalog.Get("tripo-b9e9ce29").displayName, Is.EqualTo("TRIPO"));
            Assert.That(catalog.Get("team").displayName, Is.EqualTo("CHALLENGER"));
            Assert.That(catalog.Get("tripo-b9e9ce29").resourcePath, Is.EqualTo("DollFight/Characters/TripoB9E9"));
            Assert.That(catalog.Get("team").resourcePath, Is.EqualTo("TeamCharacter"));
            Assert.That(catalog.Get("nozomi").modelFile, Is.EqualTo("nozomi.vrm"));
            Assert.That(catalog.Get("mizore").modelFile, Is.EqualTo("mizore.vrm"));
            Assert.That(catalog.Get("team").firstPersonShoulderOffset, Is.EqualTo(new Vector2(.16f, .12f)));
            Assert.That(catalog.Get("tripo-b9e9ce29").firstPersonShoulderOffset, Is.EqualTo(Vector2.zero));
        }

        [Test] public void DefaultAndClassicArgumentsResolveBothSlots()
        {
            var defaults = CharacterSelection.FromArguments(catalog, Array.Empty<string>());
            Assert.That(defaults.IdAt(0), Is.EqualTo("tripo-b9e9ce29"));
            Assert.That(defaults.IdAt(1), Is.EqualTo("team"));
            var classic = CharacterSelection.FromArguments(catalog, new[] { "-dollfightClassic" });
            Assert.That(classic.IdAt(0), Is.EqualTo("nozomi"));
            Assert.That(classic.IdAt(1), Is.EqualTo("mizore"));
            var overrides = CharacterSelection.FromArguments(catalog, new[] { "-dollfightP2", "team", "-dollfightClassic", "-dollfightP1", "mizore" });
            Assert.That(overrides.IdAt(0), Is.EqualTo("mizore"));
            Assert.That(overrides.IdAt(1), Is.EqualTo("team"));
        }

        [Test] public void SlotsAreIndependentAndMirrorSelectionIsAllowed()
        {
            var selection = CharacterSelection.FromArguments(catalog, Array.Empty<string>());
            selection.Select(0, "mizore");
            Assert.That(selection.IdAt(1), Is.EqualTo("team"));
            selection.Select(1, "mizore");
            Assert.That(selection.IdAt(0), Is.EqualTo(selection.IdAt(1)));
            selection.Select(1, "nozomi");
            Assert.That(selection.IdAt(0), Is.EqualTo("mizore"));
        }

        [Test] public void InvalidSelectionsFailWithoutChangingEitherSlot()
        {
            var selection = CharacterSelection.FromArguments(catalog, Array.Empty<string>());
            Assert.Throws<ArgumentException>(() => selection.Select(0, "missing"));
            Assert.Throws<ArgumentOutOfRangeException>(() => selection.Select(2, "team"));
            Assert.Throws<ArgumentOutOfRangeException>(() => selection.IdAt(-1));
            Assert.Throws<ArgumentException>(() => selection.Apply("nozomi", "missing"));
            Assert.That(selection.IdAt(0), Is.EqualTo("tripo-b9e9ce29"));
            Assert.That(selection.IdAt(1), Is.EqualTo("team"));
        }

        [TestCase("-dollfightP1", "missing")]
        [TestCase("-dollfightP2", "missing")]
        [TestCase("-dollfightP1", "-dollfightClassic")]
        public void InvalidCommandCharacterIsAnError(string flag, string value) =>
            Assert.Throws<ArgumentException>(() => CharacterSelection.FromArguments(catalog, new[] { flag, value }));
        [Test] public void MissingCommandValueIsAnError() =>
            Assert.Throws<ArgumentException>(() => CharacterSelection.FromArguments(catalog, new[] { "-dollfightP2" }));
        [Test] public void DuplicateCommandOptionIsAnError() =>
            Assert.Throws<ArgumentException>(() => CharacterSelection.FromArguments(catalog, new[] { "-dollfightP1", "team", "-dollfightP1", "mizore" }));

        [Test] public void SessionReloadKeepsUserSelectionAndSubsystemResetClearsIt()
        {
            var args = new[] { "-dollfightClassic" };
            var session = CharacterSelection.ForSession(catalog, args);
            session.Apply("team", "team");
            var reloaded = CharacterSelection.ForSession(catalog, args);
            Assert.That(reloaded.IdAt(0), Is.EqualTo("team"));
            Assert.That(reloaded.IdAt(1), Is.EqualTo("team"));
            ResetSession();
            Assert.That(CharacterSelection.ForSession(catalog, args).IdAt(0), Is.EqualTo("nozomi"));
        }

        [Test] public void EveryDirectoryEntryReferencesAPreparedModelAndOptionalCloth()
        {
            foreach (var character in catalog.Characters)
            {
                if (character.modelKind == "prefab")
                {
                    var prefab = Resources.Load<GameObject>(character.resourcePath);
                    Assert.That(prefab, Is.Not.Null, character.id);
                    var animator = prefab.GetComponent<Animator>();
                    Assert.That(animator, Is.Not.Null, character.id);
                    Assert.That(animator.avatar != null && animator.avatar.isHuman, Is.True, character.id);
                }
                else Assert.That(File.Exists(Path.Combine(Application.streamingAssetsPath, "DollFight", character.modelFile)), Is.True, character.id);
                if (!string.IsNullOrEmpty(character.clothFile))
                    Assert.That(File.Exists(Path.Combine(Application.streamingAssetsPath, "DollFight", character.clothFile)), Is.True, character.id);
            }
        }
    }
}
