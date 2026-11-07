using System;
using System.Collections;
using System.IO;
using System.Text;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace DollFight
{
    /// <summary>A short native acceptance path that survives the selected stage's scene reload.</summary>
    public sealed class NativeSelectionReview : MonoBehaviour
    {
        string folder;
        readonly StringBuilder report = new StringBuilder();
        DollFightDemo demo;

        public void Begin(string destination)
        {
            folder = Path.GetFullPath(destination);
            Directory.CreateDirectory(folder);
            File.Delete(Path.Combine(folder, "selection-complete.txt"));
            File.Delete(Path.Combine(folder, "selection-failed.txt"));
            DontDestroyOnLoad(gameObject);
            StartCoroutine(Review());
        }

        IEnumerator WaitReady(int previous = 0)
        {
            float deadline = Time.realtimeSinceStartup + 120;
            while (Time.realtimeSinceStartup < deadline)
            {
                demo = FindFirstObjectByType<DollFightDemo>();
                if (demo != null && demo.GetInstanceID() != previous && demo.Ready && demo.EnvironmentReady) yield break;
                yield return null;
            }
            report.AppendLine("ERROR: selected environment did not become ready within 120 seconds");
            Finish(false);
            enabled = false;
            demo = null;
        }

        IEnumerator Settle()
        {
            for (int i = 0; i < 12; i++) yield return null;
            yield return new WaitForEndOfFrame();
        }

        IEnumerator Capture(string name)
        {
            yield return Settle();
            ScreenCapture.CaptureScreenshot(Path.Combine(folder, name + ".png"));
            yield return null;
        }

        IEnumerator Review()
        {
            yield return WaitReady();
            if (demo == null) yield break;
            // Recreate the standalone backbuffer before screenshots, including hidden launches.
            Screen.SetResolution(960, 640, false);
            yield return Settle();
            Screen.SetResolution(1440, 900, false);
            yield return Settle();
            demo.OpenCharacterSelection();
            float deadline = Time.realtimeSinceStartup + 120;
            while (!demo.SelectionScreen.PortraitsReady && Time.realtimeSinceStartup < deadline) yield return null;
            if (!demo.SelectionScreen.PortraitsReady)
            {
                report.AppendLine("ERROR: selection portraits did not finish within 120 seconds");
                Finish(false); yield break;
            }
            var screen = demo.SelectionScreen;
            yield return Capture("characters-default");
            screen.FocusPlayer(0); screen.SelectCharacter(0, "mizore");
            screen.FocusPlayer(1); screen.SelectCharacter(1, "nozomi");
            yield return Capture("characters-changed");
            screen.SelectCharacter(0, "tripo-b9e9ce29"); screen.SelectCharacter(1, "tripo-b9e9ce29");
            yield return Capture("characters-mirror");
            screen.SelectCharacter(1, "team"); screen.ShowStages();
            foreach (var stage in StageCatalog.All)
            {
                screen.SelectStage(stage.id);
                yield return Capture("stages-" + stage.id);
            }
            Screen.SetResolution(960, 640, false);
            yield return Capture("stages-compact");
            screen.Back();
            bool backPassed = screen.CharactersPage;
            report.AppendLine("stageBackToCharacters=" + screen.CharactersPage);
            yield return Capture("characters-compact");
            Screen.SetResolution(1440, 900, false);
            screen.ShowStages(); screen.SelectStage("cloud");
            int previous = demo.GetInstanceID();
            screen.ConfirmSelection();
            yield return WaitReady(previous);
            if (demo == null) yield break;
            report.AppendLine($"scene={SceneManager.GetActiveScene().name} stage={demo.SelectedStageId} selectionOpen={demo.SelectionOpen} characters={string.Join(",", demo.CharacterIds)}");
            demo.playing = false; demo.Seek(2);
            yield return Capture("cloud-idle"); RecordGrounding("idle");
            float kick = demo.ReviewKickTime();
            demo.Seek(kick);
            yield return Capture("cloud-kick"); RecordGrounding("kick");
            demo.Seek(13.7f);
            yield return Capture("cloud-mid-action"); RecordGrounding("mid-action");
            demo.Seek(Mathf.Max(0, demo.PlaybackEnd - .35f)); demo.playing = true;
            deadline = Time.realtimeSinceStartup + 5;
            while (!demo.MatchFinished && Time.realtimeSinceStartup < deadline) yield return null;
            demo.playing = false;
            yield return Capture("cloud-final-hit");
            report.AppendLine($"finish replay={demo.time:F6} matchFinished={demo.MatchFinished} state={demo.CurrentFrame?.matchState} winner={demo.CurrentFrame?.matchWinner} health={string.Join(",", demo.CurrentFrame?.health ?? Array.Empty<float>())} finalContact={demo.Feedback.LastContact?.id}");
            yield return new WaitForSecondsRealtime(1.4f);
            yield return Capture("cloud-result"); RecordGrounding("finish");
            Finish(backPassed && demo.MatchFinished && SceneManager.GetActiveScene().name == "CloudDuel" && !demo.SelectionOpen);
        }

        void RecordGrounding(string sample)
        {
            report.AppendLine($"sample={sample} sourceTime={demo.time:F6} intent={demo.CurrentFrame?.intent}");
            for (int player = 0; player < 2; player++)
            {
                var actor = demo.Actors[player];
                foreach (int side in new[] { 13, 17 })
                {
                    Transform foot = actor.Bones[side];
                    Vector3 sole = foot.position;
                    bool found = false;
                    int sampled = 0;
                    foreach (var renderer in actor.ModelRoot.GetComponentsInChildren<SkinnedMeshRenderer>())
                    {
                        if (renderer.sharedMesh == null) continue;
                        var source = renderer.sharedMesh;
                        var weights = source.boneWeights;
                        if (weights == null || weights.Length == 0) continue;
                        var vertices = source.vertices;
                        var binds = source.bindposes;
                        var bones = renderer.bones;
                        var palette = new Matrix4x4[bones.Length];
                        var relevant = new bool[bones.Length];
                        for (int i = 0; i < bones.Length; i++)
                        {
                            if (bones[i] == null) continue;
                            palette[i] = bones[i].localToWorldMatrix * binds[i];
                            relevant[i] = bones[i] == foot || bones[i].IsChildOf(foot);
                        }
                        for (int i = 0; i < Mathf.Min(vertices.Length, weights.Length); i++)
                        {
                            var weight = weights[i];
                            float influence = FootWeight(relevant, weight.boneIndex0, weight.weight0) +
                                FootWeight(relevant, weight.boneIndex1, weight.weight1) +
                                FootWeight(relevant, weight.boneIndex2, weight.weight2) +
                                FootWeight(relevant, weight.boneIndex3, weight.weight3);
                            if (influence < .65f) continue;
                            Vector3 vertex = vertices[i];
                            Vector3 point = palette[weight.boneIndex0].MultiplyPoint3x4(vertex) * weight.weight0 +
                                palette[weight.boneIndex1].MultiplyPoint3x4(vertex) * weight.weight1 +
                                palette[weight.boneIndex2].MultiplyPoint3x4(vertex) * weight.weight2 +
                                palette[weight.boneIndex3].MultiplyPoint3x4(vertex) * weight.weight3;
                            sampled++;
                            if (!found || point.y < sole.y) { sole = point; found = true; }
                        }
                    }
                    bool ground = Physics.Raycast(sole + Vector3.up * 2, Vector3.down, out var hit, 10);
                    var bone = foot.position;
                    report.AppendLine(FormattableString.Invariant($"P{player + 1} {(side == 13 ? "left" : "right")} weightedSole={found} sampledVertices={sampled} method=manualWorldSkinning influenceThreshold=0.65 sole=({sole.x:F5},{sole.y:F5},{sole.z:F5}) footBone=({bone.x:F5},{bone.y:F5},{bone.z:F5}) groundHit={ground} surfaceY={(ground ? hit.point.y : float.NaN):F5} soleGap={(ground ? sole.y - hit.point.y : float.NaN):F5} collider={(ground ? hit.collider.name : "none")}"));
                }
            }
        }

        static float FootWeight(bool[] relevant, int index, float value) =>
            index >= 0 && index < relevant.Length && relevant[index] ? value : 0;

        void Finish(bool passed)
        {
            report.AppendLine("passed=" + passed);
            File.WriteAllText(Path.Combine(folder, "selection-grounding-report.txt"), report.ToString());
            File.WriteAllText(Path.Combine(folder, passed ? "selection-complete.txt" : "selection-failed.txt"), report.ToString());
            Debug.Log("DOLLFIGHT_SELECTION_REVIEW_COMPLETE passed=" + passed + " " + folder);
            if (Array.IndexOf(Environment.GetCommandLineArgs(), "-dollfightReviewQuit") >= 0) Application.Quit();
            Destroy(gameObject);
        }
    }
}
