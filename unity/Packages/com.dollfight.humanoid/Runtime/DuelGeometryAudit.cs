using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using UnityEngine;

namespace DollFight
{
    /// <summary>Opt-in native world-pose measurements; never changes the combat resolver.</summary>
    public sealed class DuelGeometryAudit : MonoBehaviour
    {
        static readonly int[] Parents = { -1, 0, 1, 2, 3, 2, 5, 6, 2, 8, 9, 0, 11, 12, 13, 0, 15, 16, 17 };
        [Serializable] sealed class Configuration { public float[] times; public Range[] ranges; }
        [Serializable] sealed class Range { public float start, end, step = 1f / 30; }
        [Serializable] sealed class CommandFile { public Command[] items; }
        [Serializable] sealed class Command
        {
            public int player;
            public string id, action, event_id, outcome;
            public float submitted, command_time, active_start, active_end, recovery_end, event_time, busy_until, hitstun_until, resolver_gap;
            public bool rejected;
        }
        [Serializable] sealed class Bone
        {
            public string name;
            public Vector3 canonical, actual, delta, rootRelativeDelta;
            public float error, rootRelativeError;
        }
        [Serializable] sealed class Capsule
        {
            public int player, boneA, boneB;
            public string zone;
            public Vector3 a, b, visualA, visualB;
            public float radius, bindingErrorA, bindingErrorB;
        }
        [Serializable] sealed class Probe
        {
            public int player, boneA, boneB;
            public string name, canonicalNearestZone, visualNearestZone;
            public float radius, canonicalGap, visualGap;
        }
        [Serializable] sealed class Player
        {
            public int player;
            public string model;
            public Bone[] bones;
            public float meanBoneError, maxBoneError, maxRootRelativeError;
        }
        [Serializable] sealed class Sample
        {
            public float requestedTime, playbackTime, frameTime, frameLag;
            public string intent, lastContact;
            public float[] health;
            public Player[] players;
            public Capsule[] hurtCapsules, attackCapsules;
            public Probe[] hypotheticalLimbProbes, activeAttackProbes;
            public Command[] commands;
            public DuelContact[] nearbyContacts;
        }
        [Serializable] sealed class Report
        {
            public string version = "dollfight-native-geometry-audit-1", error, unityVersion, scene, coordinates = "Unity world metres; X reflected once from exported stage coordinates";
            public string method = "Samples evaluated world bones after Demo.LateUpdate/EndOfFrame. Canonical FK uses the exported rest and interpolated global deltas. Capsule visual proxies translate each endpoint by its nearest canonical bone's actual displacement; binding errors are reported. Hypothetical limb probes do not imply an eligible attack, accepted command, swept contact, guard test or rendered-skin intersection.";
            public string commandSource, timeSource;
            public string[] characterIds;
            public float timelineFps, playbackDuration;
            public Sample[] samples;
        }
        string output;
        DollFightDemo demo;
        DuelTimeline timeline;
        MotionClip[] clips;
        Command[] commands = Array.Empty<Command>();
        Report report = new Report();

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
        static void Install()
        {
            string path = Argument("-dollfightGeometryAudit");
            if (string.IsNullOrEmpty(path)) return;
            var owner = new GameObject("Optional native geometry audit");
            owner.AddComponent<DuelGeometryAudit>().output = path;
        }

        static string Argument(string key)
        {
            var args = Environment.GetCommandLineArgs(); int index = Array.IndexOf(args, key);
            return index >= 0 && index + 1 < args.Length ? args[index + 1] : null;
        }

        IEnumerator Start()
        {
            float deadline = Time.realtimeSinceStartup + 90;
            while (Time.realtimeSinceStartup < deadline)
            {
                demo = FindFirstObjectByType<DollFightDemo>();
                if (demo != null && demo.Ready) break;
                yield return null;
            }
            if (demo == null || !demo.Ready) { Finish("Demo did not become ready within 90 seconds"); yield break; }
            // Let the church's one-time ready/camera setup finish before taking ownership of review playback.
            yield return null;
            if (!Prepare(out var times)) { Finish(report.error); yield break; }
            bool wasPlaying = demo.playing, views = demo.showPlayerViews;
            float previous = demo.time;
            demo.playing = false; demo.showPlayerViews = false;
            var samples = new List<Sample>(times.Count);
            try
            {
                foreach (float requested in times)
                {
                    demo.Seek(requested);
                    yield return null;
                    yield return new WaitForEndOfFrame();
                    samples.Add(Measure(requested));
                }
            }
            finally { demo.Seek(previous); demo.playing = wasPlaying; demo.showPlayerViews = views; }
            report.samples = samples.ToArray(); Finish(null);
        }

        bool Prepare(out List<float> times)
        {
            times = new List<float>();
            try
            {
                if (!Path.IsPathRooted(output)) throw new ArgumentException("Geometry audit requires an absolute output path");
                string root = Path.Combine(Application.streamingAssetsPath, "DollFight");
                timeline = JsonUtility.FromJson<DuelTimeline>(File.ReadAllText(Path.Combine(root, "duel.json")));
                clips = new[] { JsonUtility.FromJson<MotionClip>(File.ReadAllText(Path.Combine(root, "player-1-motion.json"))),
                    JsonUtility.FromJson<MotionClip>(File.ReadAllText(Path.Combine(root, "player-2-motion.json"))) };
                string configPath = Argument("-dollfightGeometryTimes");
                Configuration config = string.IsNullOrEmpty(configPath) ? new Configuration
                {
                    times = new[] { 0f, 8.6f, 8.7667f, 13.485f, 18.1208f, 18.3f, 18.56667f, 19.6f, 19.86667f, 24.3903f, 44.1f, 44.2667f },
                    ranges = new[] { new Range { start = 8.4f, end = 8.8f }, new Range { start = 18, end = 18.7f },
                        new Range { start = 19.4f, end = 20.05f }, new Range { start = 43.9f, end = 44.4f } }
                } : JsonUtility.FromJson<Configuration>(File.ReadAllText(configPath));
                if (config.times != null) foreach (float value in config.times) if (float.IsFinite(value)) times.Add(Mathf.Clamp(value, 0, demo.PlaybackEnd));
                foreach (var range in config.ranges ?? Array.Empty<Range>())
                {
                    float step = Mathf.Max(1f / 240, range.step > 0 ? range.step : 1f / 30);
                    float lastAdded = float.NegativeInfinity;
                    foreach (var frame in timeline.frames)
                        if (frame.time >= range.start - .0001f && frame.time <= range.end + .0001f && frame.time <= demo.PlaybackEnd &&
                            frame.time - lastAdded >= step - .0001f) { times.Add(frame.time); lastAdded = frame.time; }
                }
                times.Sort();
                for (int i = times.Count - 1; i > 0; i--) if (Mathf.Abs(times[i] - times[i - 1]) < .0001f) times.RemoveAt(i);
                // List entries use one-based player ids, matching the diagnostic JSON's presentation field.
                string commandPath = Argument("-dollfightGeometryCommands");
                if (!string.IsNullOrEmpty(commandPath)) commands = JsonUtility.FromJson<CommandFile>("{\"items\":" + File.ReadAllText(commandPath) + "}").items;
                report.unityVersion = Application.unityVersion; report.scene = UnityEngine.SceneManagement.SceneManager.GetActiveScene().name;
                report.characterIds = demo.CharacterIds; report.timelineFps = timeline.fps; report.playbackDuration = demo.Duration;
                report.commandSource = commandPath; report.timeSource = configPath ?? "built-in focused miss/recovery windows at timeline frame times plus exact events";
                return true;
            }
            catch (Exception error) { report.error = error.ToString(); return false; }
        }

        Sample Measure(float requested)
        {
            var frame = demo.CurrentFrame;
            var canonical = new[] { Canonical(clips[0], demo.time), Canonical(clips[1], demo.time) };
            var atFrame = new[] { Canonical(clips[0], frame.time), Canonical(clips[1], frame.time) };
            var actual = new Vector3[2][]; var players = new Player[2];
            for (int p = 0; p < 2; p++)
            {
                actual[p] = Array.ConvertAll(demo.Actors[p].Bones, bone => bone.position);
                var bones = new Bone[19]; float sum = 0, maximum = 0, relativeMaximum = 0;
                Vector3 rootDelta = actual[p][0] - canonical[p][0];
                for (int b = 0; b < bones.Length; b++)
                {
                    Vector3 delta = actual[p][b] - canonical[p][b], relative = delta - rootDelta;
                    bones[b] = new Bone { name = HumanoidReplay.BoneOrder[b].ToString(), canonical = canonical[p][b], actual = actual[p][b], delta = delta,
                        error = delta.magnitude, rootRelativeDelta = relative, rootRelativeError = relative.magnitude };
                    sum += delta.magnitude; maximum = Mathf.Max(maximum, delta.magnitude); relativeMaximum = Mathf.Max(relativeMaximum, relative.magnitude);
                }
                players[p] = new Player { player = p + 1, model = demo.SelectedCharacter(p).id, bones = bones,
                    meanBoneError = sum / 19, maxBoneError = maximum, maxRootRelativeError = relativeMaximum };
            }
            var hurt = Convert(frame.hurtCapsules, atFrame, actual); var attack = Convert(frame.attackCapsules, atFrame, actual);
            var probes = new List<Probe>(); var active = new List<Probe>();
            for (int p = 0; p < 2; p++) foreach (int bone in new[] { 7, 10, 13, 17 })
            {
                int end = bone >= 13 ? bone + 1 : bone; float radius = bone >= 13 ? .12f : .09f;
                probes.Add(Compare(p, bone, end, HumanoidReplay.BoneOrder[bone].ToString(), radius,
                    canonical[p][bone], canonical[p][end], actual[p][bone], actual[p][end], hurt));
            }
            foreach (var capsule in attack) active.Add(Compare(capsule.player - 1, capsule.boneA, capsule.boneB, "exported active attack", capsule.radius,
                capsule.a, capsule.b, capsule.visualA, capsule.visualB, hurt));
            var nearby = new List<DuelContact>(); foreach (var contact in timeline.contacts ?? Array.Empty<DuelContact>()) if (Mathf.Abs(contact.time - demo.time) <= .3f) nearby.Add(contact);
            var matched = new List<Command>(); foreach (var command in commands ?? Array.Empty<Command>())
                if (demo.time >= command.submitted - .15f && demo.time <= Mathf.Max(command.recovery_end, command.event_time) + .15f) matched.Add(command);
            return new Sample { requestedTime = requested, playbackTime = demo.time, frameTime = frame.time, frameLag = demo.time - frame.time,
                intent = frame.intent, lastContact = frame.lastContact, health = frame.health, players = players, hurtCapsules = hurt, attackCapsules = attack,
                hypotheticalLimbProbes = probes.ToArray(), activeAttackProbes = active.ToArray(), nearbyContacts = nearby.ToArray(), commands = matched.ToArray() };
        }

        static Vector3[] Canonical(MotionClip clip, float time)
        {
            int low = 0, high = clip.frames.Length - 1;
            while (low < high) { int middle = (low + high + 1) / 2; if (clip.frames[middle].time <= time) low = middle; else high = middle - 1; }
            var a = clip.frames[low]; var b = clip.frames[Mathf.Min(low + 1, clip.frames.Length - 1)];
            float alpha = b.time > a.time ? Mathf.Clamp01((time - a.time) / (b.time - a.time)) : 0;
            var points = new Vector3[19]; points[0] = Vector3.Lerp(a.root, b.root, alpha);
            for (int i = 1; i < points.Length; i++) points[i] = points[Parents[i]] + Quaternion.Slerp(a.rotations[Parents[i]], b.rotations[Parents[i]], alpha) * (clip.rest[i] - clip.rest[Parents[i]]);
            return Array.ConvertAll(points, HumanoidReplay.StageToUnity);
        }

        static Capsule[] Convert(DuelCapsule[] source, Vector3[][] canonical, Vector3[][] actual)
        {
            return Array.ConvertAll(source ?? Array.Empty<DuelCapsule>(), capsule =>
            {
                int p = capsule.player; Vector3 a = HumanoidReplay.StageToUnity(capsule.a), b = HumanoidReplay.StageToUnity(capsule.b);
                int boneA = Nearest(a, canonical[p]), boneB = Nearest(b, canonical[p]);
                return new Capsule { player = p + 1, zone = capsule.zone, a = a, b = b, radius = capsule.radius, boneA = boneA, boneB = boneB,
                    bindingErrorA = Vector3.Distance(a, canonical[p][boneA]), bindingErrorB = Vector3.Distance(b, canonical[p][boneB]),
                    visualA = a + actual[p][boneA] - canonical[p][boneA], visualB = b + actual[p][boneB] - canonical[p][boneB] };
            });
        }

        static int Nearest(Vector3 point, Vector3[] bones)
        {
            int closest = 0; for (int i = 1; i < bones.Length; i++) if ((point - bones[i]).sqrMagnitude < (point - bones[closest]).sqrMagnitude) closest = i;
            return closest;
        }

        static Probe Compare(int player, int boneA, int boneB, string name, float radius, Vector3 a, Vector3 b, Vector3 visualA, Vector3 visualB, Capsule[] hurt)
        {
            var probe = new Probe { player = player + 1, boneA = boneA, boneB = boneB, name = name, radius = radius, canonicalGap = 999, visualGap = 999 };
            foreach (var target in hurt)
            {
                if (target.player == player + 1) continue;
                float canonicalGap = SegmentDistance(a, b, target.a, target.b) - radius - target.radius;
                float visualGap = SegmentDistance(visualA, visualB, target.visualA, target.visualB) - radius - target.radius;
                if (canonicalGap < probe.canonicalGap) { probe.canonicalGap = canonicalGap; probe.canonicalNearestZone = target.zone; }
                if (visualGap < probe.visualGap) { probe.visualGap = visualGap; probe.visualNearestZone = target.zone; }
            }
            return probe;
        }

        static float PointDistance(Vector3 p, Vector3 a, Vector3 b)
        {
            Vector3 axis = b - a; float t = axis.sqrMagnitude > 1e-12f ? Mathf.Clamp01(Vector3.Dot(p - a, axis) / axis.sqrMagnitude) : 0;
            return Vector3.Distance(p, a + axis * t);
        }

        static float SegmentDistance(Vector3 a, Vector3 b, Vector3 c, Vector3 d)
        {
            Vector3 u = b - a, v = d - c, w = a - c;
            float uu = Vector3.Dot(u, u), uv = Vector3.Dot(u, v), vv = Vector3.Dot(v, v), uw = Vector3.Dot(u, w), vw = Vector3.Dot(v, w);
            float denominator = uu * vv - uv * uv;
            float result = Mathf.Min(Mathf.Min(PointDistance(a, c, d), PointDistance(b, c, d)), Mathf.Min(PointDistance(c, a, b), PointDistance(d, a, b)));
            if (denominator > 1e-12f)
            {
                float s = (uv * vw - vv * uw) / denominator, t = (uu * vw - uv * uw) / denominator;
                if (s >= 0 && s <= 1 && t >= 0 && t <= 1) result = Mathf.Min(result, Vector3.Distance(a + s * u, c + t * v));
            }
            return result;
        }

        void Finish(string error)
        {
            report.error = error;
            try { Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(output))); File.WriteAllText(output, JsonUtility.ToJson(report, true)); }
            catch (Exception exception) { Debug.LogException(exception); }
            Debug.Log(error == null ? "DOLLFIGHT_GEOMETRY_AUDIT_COMPLETE " + output : "DOLLFIGHT_GEOMETRY_AUDIT_FAILED " + error);
            if (Array.Exists(Environment.GetCommandLineArgs(), value => value == "-dollfightReviewQuit")) Application.Quit();
            Destroy(gameObject);
        }
    }
}
