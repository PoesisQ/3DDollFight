using System.Collections.Generic;
using UnityEngine;

namespace DollFight
{
    // Different shoes can extend well below the mapped Foot bone. Sample their
    // actual weighted surface, once in bind pose, rather than assuming that an
    // ankle at 9 cm means the shoe is grounded. Only used for a new FBX body.
    public sealed class AvatarSoleContact
    {
        struct Sample { public Vector3 vertex; public BoneWeight weight; public int mesh; }
        sealed class Skin { public Transform[] bones; public Matrix4x4[] bind, palette; }
        readonly List<Skin> skins = new List<Skin>();
        readonly List<Sample>[] samples = { new List<Sample>(), new List<Sample>() };
        readonly Transform[] bones;
        float offset;
        public float RestFloorOffset { get; private set; }
        public float MaximumCorrection { get; private set; }

        public AvatarSoleContact(Transform root, Transform[] bones)
        {
            this.bones = bones;
            foreach (var renderer in root.GetComponentsInChildren<SkinnedMeshRenderer>())
            {
                var mesh = renderer.sharedMesh;
                var skin = new Skin { bones = renderer.bones, bind = mesh.bindposes, palette = new Matrix4x4[renderer.bones.Length] };
                int meshIndex = skins.Count; skins.Add(skin); UpdatePalette(skin);
                Vector3[] vertices = mesh.vertices; BoneWeight[] weights = mesh.boneWeights;
                for (int side = 0; side < 2; side++)
                {
                    Transform foot = bones[side == 0 ? 13 : 17];
                    bool[] relevant = System.Array.ConvertAll(skin.bones, b => b == foot || b.IsChildOf(foot));
                    // Keep minima across a 4 x 8 foot-local grid. This includes
                    // heel and toe support points without skinning a dense mesh.
                    var cells = new Dictionary<Vector2Int, Sample>();
                    var heights = new Dictionary<Vector2Int, float>();
                    for (int v = 0; v < vertices.Length; v++)
                    {
                        var w = weights[v];
                        float influence = (relevant[w.boneIndex0] ? w.weight0 : 0) + (relevant[w.boneIndex1] ? w.weight1 : 0) +
                            (relevant[w.boneIndex2] ? w.weight2 : 0) + (relevant[w.boneIndex3] ? w.weight3 : 0);
                        if (influence < 0.65f) continue;
                        var sample = new Sample { vertex = vertices[v], weight = w, mesh = meshIndex };
                        Vector3 world = Position(sample), p = root.InverseTransformPoint(world);
                        var cell = new Vector2Int(Mathf.FloorToInt(p.x / 0.025f), Mathf.FloorToInt(p.z / 0.025f));
                        if (!heights.TryGetValue(cell, out float y) || world.y < y)
                        { heights[cell] = world.y; cells[cell] = sample; }
                    }
                    samples[side].AddRange(cells.Values);
                }
            }
            if (samples[0].Count == 0 || samples[1].Count == 0)
                throw new System.ArgumentException("New avatar has no weighted shoe surface for contact calibration");
            RestFloorOffset = -Mathf.Min(Height(0), Height(1));
        }

        void UpdatePalette(Skin skin)
        {
            for (int i = 0; i < skin.palette.Length; i++) skin.palette[i] = skin.bones[i].localToWorldMatrix * skin.bind[i];
        }
        Vector3 Position(Sample s)
        {
            var p = skins[s.mesh].palette; var w = s.weight; var v = s.vertex;
            return p[w.boneIndex0].MultiplyPoint3x4(v) * w.weight0 + p[w.boneIndex1].MultiplyPoint3x4(v) * w.weight1 +
                p[w.boneIndex2].MultiplyPoint3x4(v) * w.weight2 + p[w.boneIndex3].MultiplyPoint3x4(v) * w.weight3;
        }
        float Height(int side)
        {
            float height = float.PositiveInfinity;
            foreach (var sample in samples[side]) height = Mathf.Min(height, Position(sample).y);
            return height;
        }

        public void Apply(Vector3[] source, Vector3[] rest, float ratio, float dt, bool reset)
        {
            foreach (var skin in skins) UpdatePalette(skin);
            var errors = Vector2.zero; var weight = Vector2.zero;
            for (int side = 0; side < 2; side++)
            {
                int foot = side == 0 ? 13 : 17;
                float altitude = Mathf.Min(source[foot].y - rest[foot].y, source[foot + 1].y - rest[foot + 1].y);
                weight[side] = 1 - Mathf.SmoothStep(0, 1, Mathf.InverseLerp(0.025f, 0.14f, altitude));
                errors[side] = Mathf.Clamp(Mathf.Max(0, altitude) * ratio - Height(side), -0.16f, 0.16f);
            }
            float total = weight.x + weight.y;
            float desired = total > 0 ? Vector2.Dot(errors, weight) / total * Mathf.Max(weight.x, weight.y) : 0;
            offset = reset ? desired : Mathf.Lerp(offset, desired, 1 - Mathf.Exp(-dt / 0.045f));
            bones[0].position += Vector3.up * offset;
            MaximumCorrection = Mathf.Abs(offset);
            for (int side = 0; side < 2; side++)
            {
                int foot = side == 0 ? 13 : 17;
                float remaining = Mathf.Clamp((errors[side] - offset) * weight[side], -0.075f, 0.075f);
                HumanoidLimbIK.Solve(bones[foot - 2], bones[foot - 1], bones[foot], bones[foot].position + Vector3.up * remaining);
            }
        }
    }

    public static class HumanoidLimbIK
    {
        public static void Solve(Transform a, Transform b, Transform c, Vector3 target)
        {
            Quaternion endRotation = c.rotation;
            float upper = Vector3.Distance(a.position, b.position), lower = Vector3.Distance(b.position, c.position);
            Vector3 axis = target - a.position;
            float distance = Mathf.Clamp(axis.magnitude, Mathf.Abs(upper - lower) + 0.001f, upper + lower - 0.003f);
            axis.Normalize(); target = a.position + axis * distance;
            Vector3 pole = Vector3.ProjectOnPlane(b.position - a.position, axis);
            if (pole.sqrMagnitude < 0.000001f) pole = Vector3.ProjectOnPlane(a.forward, axis);
            float along = (upper * upper + distance * distance - lower * lower) / (2 * distance);
            Vector3 middle = a.position + axis * along + pole.normalized * Mathf.Sqrt(Mathf.Max(0, upper * upper - along * along));
            a.rotation = Quaternion.FromToRotation(b.position - a.position, middle - a.position) * a.rotation;
            b.rotation = Quaternion.FromToRotation(c.position - b.position, target - b.position) * b.rotation;
            c.rotation = endRotation;
        }
    }
}
