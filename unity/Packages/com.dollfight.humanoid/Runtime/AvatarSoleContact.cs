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
        /// <summary>Up direction of each shoe, expressed in that foot bone's own frame.</summary>
        readonly Vector3[] soleUp = { Vector3.up, Vector3.up };
        readonly bool[] soleUpKnown = new bool[2];
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
            // Fit the sole plane once, in the pose the model was imported in.
            // Keeping it in foot-local space means it survives every leg pose:
            // whoever drives the body can level the shoe without knowing which
            // way this particular mesh was modelled.
            for (int side = 0; side < 2; side++) soleUpKnown[side] = FitSoleUp(side, out soleUp[side]);
        }

        /// <summary>World height of the lowest point of either shoe in the current pose.</summary>
        public float LowestSole()
        {
            foreach (var skin in skins) UpdatePalette(skin);
            return Mathf.Min(Height(0), Height(1));
        }

        /// <summary>
        /// World height of the lowest point of one shoe, 0 = left, 1 = right.
        ///
        /// Posing a foot is only right while it is standing on something: the
        /// clip lifts its feet when it walks, and levelling a swinging shoe
        /// flattens the step. This is how the caller tells the two apart.
        /// </summary>
        public float SoleHeight(int side)
        {
            foreach (var skin in skins) UpdatePalette(skin);
            return Height(side == 0 ? 0 : 1);
        }

        /// <summary>Re-reads the bone transforms after something moved them.</summary>
        public void Refresh()
        {
            foreach (var skin in skins) UpdatePalette(skin);
        }

        /// <summary>
        /// The direction the shoe's sampled surface is thinnest in, where the
        /// shoe is now, orientated to agree with <paramref name="reference"/>.
        ///
        /// <see cref="TrySoleUp"/> answers "which way is up for this shoe" from
        /// the imported pose, and is what a foot is aimed with. This answers
        /// the different question "where does the shoe stand at this instant",
        /// independently of the first: the thinnest axis of the sampled
        /// surface, by principal axes, with no direction and no pose assumed
        /// inside the fit. It is a measurement, and nothing aims with it.
        ///
        /// It used to be an input, and that is what the 2026-11-25 12:01
        /// recording shows. The fit was restricted to a contact band taken
        /// *along* the modelled direction carried into the current pose - but
        /// the pose is precisely what is wrong, so the band was cut at the
        /// angle the shoe was already rolled to, caught the entire shoe
        /// (`soleBand=18/18`), and fitted a plane through the upper. A shoe
        /// that had just been levelled read 28.7 degrees off; the caller aimed
        /// at that, and standing still came out rolled further onto its outer
        /// edge while a kick - which skips levelling - still looked right.
        /// Referencing a measurement by the pose it is meant to correct is a
        /// feedback loop. The only thing the pose may decide is the sign.
        /// </summary>
        public bool TrySoleNormal(int side, Vector3 reference, out Vector3 worldUp)
        {
            worldUp = Vector3.up;
            var points = samples[side];
            if (points.Count < 12) return false;
            Refresh();
            var world = new List<Vector3>(points.Count);
            foreach (var point in points) world.Add(Position(point));
            if (!ThinDirection(world, out worldUp)) return false;
            // A principal axis has no sign. It has to be turned to face the
            // same way as the modelled sole before the band is cut, or the band
            // is taken from the top of the shoe and the fit describes the
            // instep. This is the only thing the pose is allowed to decide.
            if (Vector3.Dot(worldUp, reference) < 0f) worldUp = -worldUp;
            // Only the patch that touches, and the band is measured along the
            // fit itself - never shaped by the direction the caller passed in.
            // That is the whole difference from the version that lied: the axis
            // it was banded on *was* the pose, so the band was cut at the angle
            // the shoe had already been rolled to.
            var contact = Band(world, worldUp);
            if (contact.Count >= 6 && ThinDirection(contact, out Vector3 refined))
            {
                if (Vector3.Dot(refined, worldUp) < 0f) refined = -refined;
                worldUp = refined;
            }
            if (Vector3.Dot(worldUp, reference) < 0f) worldUp = -worldUp;
            return true;
        }

        /// <summary>
        /// The points within 20 mm of the lowest one along <paramref name="axis"/>:
        /// what would touch if the shoe were set down that way. The rest of the
        /// sampled surface is upper and ankle, which do not lie in the sole's
        /// plane and drag a fit through them off it.
        /// </summary>
        static List<Vector3> Band(List<Vector3> points, Vector3 axis, float width = 0.02f)
        {
            float lowest = float.PositiveInfinity;
            foreach (var p in points) lowest = Mathf.Min(lowest, Vector3.Dot(p, axis));
            var contact = new List<Vector3>(points.Count);
            foreach (var p in points)
                if (Vector3.Dot(p, axis) <= lowest + width) contact.Add(p);
            return contact;
        }

        /// <summary>The fitted plane's own normal, pointing up.</summary>
        public bool TrySoleNormal(int side, out Vector3 worldUp)
        {
            return TrySoleNormal(side, Vector3.up, out worldUp);
        }

        /// <summary>
        /// The shoe's up direction in its foot bone's frame, fitted to the sole
        /// in the pose the model was imported in.
        /// </summary>
        public bool TrySoleUp(int side, out Vector3 localUp)
        {
            localUp = soleUp[side];
            return soleUpKnown[side];
        }

        /// <summary>
        /// Fits the modelled sole. Always answers something usable: a model
        /// authored standing on the floor has its sole perpendicular to world
        /// up by definition, in every direction that matters here, so the
        /// imported pose's own up is a truthful fallback rather than a guess.
        ///
        /// The fit proper is the surface's thinnest axis, not "height over x
        /// and z". A humanoid foot bone routinely points *down the foot*
        /// rather than up out of the sole: measured on the Tripo prefab, world
        /// up in foot space is (-0.50, -0.68, 0.54), so writing the plane as
        /// y = a*x + b*z + c in that frame describes a plane through the
        /// ankle, and the old "is this really a sole" guard (up.y >= 0.35)
        /// rejected the fit on every frame - leaving the caller to aim the
        /// bone's own Y axis at the floor. The thinnest axis needs no frame at
        /// all, so it answers the same question for any rig.
        ///
        /// The contact band is taken along *world* up, which is only meaningful
        /// because of when this runs: the model is standing on the floor in its
        /// imported pose, so the patch that touches is the lowest 20 mm in
        /// world Y. That is the one moment the question has an unambiguous
        /// answer, and it is why the samples are taken there and nowhere else.
        /// </summary>
        bool FitSoleUp(int side, out Vector3 localUp)
        {
            var foot = bones[side == 0 ? 13 : 17];
            localUp = foot.InverseTransformDirection(Vector3.up);
            var points = samples[side];
            if (points.Count < 12) return false;
            var world = new List<Vector3>(points.Count);
            foreach (var point in points) world.Add(Position(point));
            if (!ThinDirection(world, out Vector3 normal)) return false;
            if (Vector3.Dot(normal, Vector3.up) < 0f) normal = -normal;
            // Only the patch that touches. A heeled shoe carries its arch about
            // 15 mm above the contact points (measured: 17 cells within 4 mm,
            // 15 more at 15-23 mm, 2 at the ankle), and a plane through all of
            // them is a plane through neither.
            var contact = Band(world, Vector3.up);
            if (contact.Count >= 6 && ThinDirection(contact, out Vector3 refined))
            {
                if (Vector3.Dot(refined, Vector3.up) < 0f) refined = -refined;
                if (refined.y > 0.5f) normal = refined;
            }
            // A fit that is not close to horizontal is not this shoe's sole -
            // the model is on its toes, or the sampling caught the upper - and
            // the imported pose's up, which is right by construction, is kept.
            if (normal.y < 0.5f) return true;
            localUp = foot.InverseTransformDirection(normal);
            return true;
        }

        /// <summary>
        /// The direction a set of points is thinnest in - the normal of the
        /// plane that best describes them.
        ///
        /// Principal axes of the covariance, by Jacobi rotations: the smallest
        /// diagonal after the sweeps is the smallest variance, and the rotation
        /// column that produced it is the direction. Nothing here assumes which
        /// way the foot bone points, which is the whole point.
        /// </summary>
        static bool ThinDirection(List<Vector3> points, out Vector3 normal)
        {
            normal = Vector3.up;
            if (points.Count < 6) return false;
            Vector3 mean = Vector3.zero;
            foreach (var p in points) mean += p;
            mean /= points.Count;
            double[,] c = new double[3, 3];
            foreach (var p in points)
            {
                Vector3 d = p - mean;
                c[0, 0] += d.x * d.x; c[0, 1] += d.x * d.y; c[0, 2] += d.x * d.z;
                c[1, 0] += d.y * d.x; c[1, 1] += d.y * d.y; c[1, 2] += d.y * d.z;
                c[2, 0] += d.z * d.x; c[2, 1] += d.z * d.y; c[2, 2] += d.z * d.z;
            }
            double[,] v = { { 1, 0, 0 }, { 0, 1, 0 }, { 0, 0, 1 } };
            for (int sweep = 0; sweep < 12; sweep++)
            {
                if (System.Math.Abs(c[0, 1]) + System.Math.Abs(c[0, 2]) + System.Math.Abs(c[1, 2]) < 1e-12) break;
                for (int p = 0; p < 2; p++)
                    for (int q = p + 1; q < 3; q++)
                    {
                        if (System.Math.Abs(c[p, q]) < 1e-15) continue;
                        double theta = (c[q, q] - c[p, p]) / (2 * c[p, q]);
                        double t = theta == 0 ? 1 : System.Math.Sign(theta) /
                            (System.Math.Abs(theta) + System.Math.Sqrt(theta * theta + 1));
                        double cs = 1 / System.Math.Sqrt(t * t + 1), sn = t * cs;
                        for (int k = 0; k < 3; k++)
                        {
                            double kp = c[k, p], kq = c[k, q];
                            c[k, p] = cs * kp - sn * kq; c[k, q] = sn * kp + cs * kq;
                        }
                        for (int k = 0; k < 3; k++)
                        {
                            double pk = c[p, k], qk = c[q, k];
                            c[p, k] = cs * pk - sn * qk; c[q, k] = sn * pk + cs * qk;
                        }
                        for (int k = 0; k < 3; k++)
                        {
                            double kp = v[k, p], kq = v[k, q];
                            v[k, p] = cs * kp - sn * kq; v[k, q] = sn * kp + cs * kq;
                        }
                    }
            }
            int smallest = 0;
            if (c[1, 1] < c[smallest, smallest]) smallest = 1;
            if (c[2, 2] < c[smallest, smallest]) smallest = 2;
            var axis = new Vector3((float)v[0, smallest], (float)v[1, smallest], (float)v[2, smallest]);
            if (axis.sqrMagnitude < 1e-12f) return false;
            normal = axis.normalized;
            return true;
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
