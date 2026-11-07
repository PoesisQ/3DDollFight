using System;
using System.Collections.Generic;
using System.IO;
using UnityEngine;

namespace DollFight
{
    [Serializable] public sealed class CharacterDefinition
    {
        public string id, displayName, modelKind, resourcePath, modelFile, clothFile;
        // X = backward metres, Y = downward metres in the view-only shoulder rig.
        public Vector2 firstPersonShoulderOffset;
    }

    /// <summary>Model configuration is independent of the two player motion slots.</summary>
    public sealed class CharacterCatalog
    {
        [Serializable] sealed class Document { public CharacterDefinition[] characters; }
        readonly Dictionary<string, CharacterDefinition> byId = new Dictionary<string, CharacterDefinition>(StringComparer.Ordinal);
        public IReadOnlyList<CharacterDefinition> Characters { get; }

        CharacterCatalog(CharacterDefinition[] characters)
        {
            if (characters == null || characters.Length == 0) throw new InvalidDataException("Character directory is empty");
            foreach (var character in characters)
            {
                if (character == null || string.IsNullOrWhiteSpace(character.id) || string.IsNullOrWhiteSpace(character.displayName))
                    throw new InvalidDataException("Character directory requires stable IDs and display names");
                if (byId.ContainsKey(character.id)) throw new InvalidDataException("Duplicate character ID: " + character.id);
                if (character.modelKind == "prefab")
                {
                    if (!SafeRelativePath(character.resourcePath) || !string.IsNullOrEmpty(character.modelFile))
                        throw new InvalidDataException("Character prefab requires a Resources path: " + character.id);
                }
                else if (character.modelKind == "vrm")
                {
                    if (!SafeRelativePath(character.modelFile) || !character.modelFile.EndsWith(".vrm", StringComparison.OrdinalIgnoreCase) || !string.IsNullOrEmpty(character.resourcePath))
                        throw new InvalidDataException("Character VRM requires a local model file: " + character.id);
                }
                else throw new InvalidDataException("Unknown character model kind: " + character.id);
                if (!string.IsNullOrEmpty(character.clothFile) && !SafeRelativePath(character.clothFile))
                    throw new InvalidDataException("Invalid character cloth path: " + character.id);
                var offset = character.firstPersonShoulderOffset;
                if (!float.IsFinite(offset.x) || !float.IsFinite(offset.y) || offset.x < 0 || offset.y < 0)
                    throw new InvalidDataException("Invalid first-person shoulder offset: " + character.id);
                byId.Add(character.id, character);
            }
            Characters = Array.AsReadOnly(characters);
        }

        static bool SafeRelativePath(string value) => !string.IsNullOrWhiteSpace(value) && !Path.IsPathRooted(value) &&
            !value.Contains("..") && !value.Contains(":") && !value.Contains("\\");

        public static CharacterCatalog Load()
        {
            var asset = Resources.Load<TextAsset>("DollFight/Characters");
            if (asset == null) throw new FileNotFoundException("Missing Resources/DollFight/Characters.json");
            return new CharacterCatalog(JsonUtility.FromJson<Document>(asset.text)?.characters);
        }

        public CharacterDefinition Get(string id)
        {
            if (id == null || !byId.TryGetValue(id, out var character)) throw new ArgumentException("Unknown character ID: " + id, nameof(id));
            return character;
        }
    }

    /// <summary>Zero-based independent player slots. Session choices survive scene reloads only.</summary>
    public sealed class CharacterSelection
    {
        readonly CharacterCatalog catalog;
        readonly string[] ids = new string[2];
        bool persists;
        static string[] sessionIds;

        CharacterSelection(CharacterCatalog catalog, string playerOne, string playerTwo)
        {
            this.catalog = catalog ?? throw new ArgumentNullException(nameof(catalog));
            Apply(playerOne, playerTwo);
        }

        public static CharacterSelection FromArguments(CharacterCatalog catalog, string[] args)
        {
            args = args ?? Array.Empty<string>();
            bool classic = Array.IndexOf(args, "-dollfightClassic") >= 0;
            var selected = new[] { classic ? "nozomi" : "tripo-b9e9ce29", classic ? "mizore" : "team" };
            for (int player = 0; player < 2; player++)
            {
                string key = "-dollfightP" + (player + 1);
                int index = Array.IndexOf(args, key);
                if (index < 0) continue;
                if (Array.LastIndexOf(args, key) != index) throw new ArgumentException("Duplicate character option: " + key);
                if (index + 1 >= args.Length || string.IsNullOrWhiteSpace(args[index + 1]) || args[index + 1].StartsWith("-", StringComparison.Ordinal))
                    throw new ArgumentException("Missing character ID after " + key);
                selected[player] = args[index + 1];
            }
            return new CharacterSelection(catalog, selected[0], selected[1]);
        }

        public static CharacterSelection ForSession(CharacterCatalog catalog, string[] args)
        {
            var selection = sessionIds == null ? FromArguments(catalog, args) : new CharacterSelection(catalog, sessionIds[0], sessionIds[1]);
            selection.persists = true;
            selection.Persist();
            return selection;
        }

        public string IdAt(int player) { ValidatePlayer(player); return ids[player]; }
        public void Select(int player, string id)
        {
            ValidatePlayer(player); catalog.Get(id);
            ids[player] = id; Persist();
        }

        public void Apply(string playerOne, string playerTwo)
        {
            catalog.Get(playerOne); catalog.Get(playerTwo);
            ids[0] = playerOne; ids[1] = playerTwo; Persist();
        }

        static void ValidatePlayer(int player)
        {
            if (player < 0 || player > 1) throw new ArgumentOutOfRangeException(nameof(player), "Player slot must be 0 or 1");
        }
        void Persist() { if (persists) sessionIds = new[] { ids[0], ids[1] }; }
        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.SubsystemRegistration)]
        static void ResetSession() { sessionIds = null; }
    }
}
