using System;
using System.Collections.Generic;

namespace DollFight
{
    [Serializable]
    public sealed class StageDefinition
    {
        public string id, displayName, subtitle, sceneName, previewResource;

        public StageDefinition(string id, string displayName, string subtitle, string sceneName)
        {
            this.id = id; this.displayName = displayName; this.subtitle = subtitle; this.sceneName = sceneName;
            previewResource = "DollFight/Selection/Stages/" + id;
        }
    }

    /// <summary>The same allowlist drives the visible stage strip and native scene loading.</summary>
    public static class StageCatalog
    {
        public static readonly IReadOnlyList<StageDefinition> All = Array.AsReadOnly(new[] {
            new StageDefinition("underground", "UNDERGROUND", "地下竞技场", "DollFight"),
            new StageDefinition("saint-maurice", "SAINT-MAURICE", "圣莫里斯教堂", "SaintMauriceDuel"),
            new StageDefinition("cloud", "CLOUD SANCTUM", "云海遗迹", "CloudDuel")
        });

        public static StageDefinition Get(string id)
        {
            foreach (var stage in All) if (stage.id == id) return stage;
            throw new ArgumentException("Unknown stage ID: " + id, nameof(id));
        }
    }
}
