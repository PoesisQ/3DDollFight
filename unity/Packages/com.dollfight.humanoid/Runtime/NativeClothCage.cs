using System;
using UnityEngine;
using UnityEngine.Rendering;

namespace DollFight
{
    [Serializable] public class ClothCageData
    {
        public int segments, rows;
        public Vector3[] rest;
        public float[] capsuleRadii;
    }

    // PhysX cloth simulates 216 control vertices, while the original dense
    // dress keeps its topology, textures and GPU skinning weights.
    public sealed class NativeClothCage : MonoBehaviour
    {
        Cloth cloth;
        Transform[] controls;
        Transform proxy;
        Mesh simulationMesh;
        Material simulationMaterial;
        int[] particleToControl;
        Transform anchorHip;
        Vector3[] restInHip;
        Vector3[] restInGuide;
        Transform[] guides;
        HumanoidReplay actor;
        Vector3 down, waist;
        Vector3[] radial;
        float[] lifts, smoothed;
        int rows;
        static readonly int[] Thighs = { 11, 15 };
        int anchorCount, drawnFrames;
        public float MaximumAnchorError { get; private set; }
        public float MaximumDisplacement { get; private set; }

        public void Initialize(HumanoidReplay actor, ClothCageData data)
        {
            this.actor = actor; rows = data.rows;
            if (data == null || data.rest == null || data.segments * data.rows != data.rest.Length)
                throw new ArgumentException("Invalid cloth cage topology");
            var transforms = actor.Instance.GetComponentsInChildren<Transform>();
            controls = new Transform[data.rest.Length];
            for (int i = 0; i < controls.Length; i++)
            {
                string boneName = $"DF_Cage_{i / data.segments}_{i % data.segments}";
                controls[i] = Array.Find(transforms, t => t.name == boneName);
                if (controls[i] == null) throw new ArgumentException("Missing cloth control " + boneName);
            }
            var go = new GameObject("Native cloth simulation cage");
            go.transform.SetParent(actor.Instance.transform, false);
            go.layer = 31;
            proxy = go.transform;
            Vector3[] vertices = Array.ConvertAll(data.rest, HumanoidReplay.StageToUnity);
            int[] triangles = new int[(data.rows - 1) * data.segments * 6];
            int cursor = 0;
            for (int row = 0; row < data.rows - 1; row++)
                for (int col = 0; col < data.segments; col++)
                {
                    int a = row * data.segments + col;
                    int b = row * data.segments + (col + 1) % data.segments;
                    triangles[cursor++] = a; triangles[cursor++] = a + data.segments; triangles[cursor++] = b;
                    triangles[cursor++] = b; triangles[cursor++] = a + data.segments; triangles[cursor++] = b + data.segments;
                }
            var hip = actor.Bones[0];
            anchorHip = hip; anchorCount = data.segments;
            restInHip = Array.ConvertAll(vertices, p => hip.InverseTransformPoint(proxy.TransformPoint(p)));
            guides = new Transform[data.segments];
            radial = new Vector3[data.segments];
            lifts = new float[data.segments]; smoothed = new float[data.segments];
            Vector3 hem = Vector3.zero;
            for (int col = 0; col < data.segments; col++)
            { waist += restInHip[col] / data.segments; hem += restInHip[(data.rows - 1) * data.segments + col] / data.segments; }
            down = (hem - waist).normalized;
            var bindposes = new Matrix4x4[data.segments];
            restInGuide = new Vector3[vertices.Length];
            for (int col = 0; col < data.segments; col++)
            {
                guides[col] = new GameObject("Skirt pose guide " + col).transform;
                guides[col].SetParent(hip, false);
                guides[col].localPosition = restInHip[col];
                radial[col] = Vector3.ProjectOnPlane(restInHip[col] - waist, down).normalized;
                bindposes[col] = guides[col].worldToLocalMatrix * proxy.localToWorldMatrix;
            }
            simulationMesh = new Mesh { name = "DollFight cloth cage (216 vertices)", vertices = vertices, triangles = triangles };
            var weights = new BoneWeight[vertices.Length];
            for (int i = 0; i < weights.Length; i++)
            {
                int col = i % data.segments;
                weights[i] = new BoneWeight { boneIndex0 = col, weight0 = 1 };
                restInGuide[i] = guides[col].InverseTransformPoint(proxy.TransformPoint(vertices[i]));
            }
            simulationMesh.boneWeights = weights;
            simulationMesh.bindposes = bindposes;
            simulationMesh.RecalculateNormals(); simulationMesh.RecalculateBounds();
            var skin = go.AddComponent<SkinnedMeshRenderer>();
            skin.sharedMesh = simulationMesh; skin.bones = guides;
            // Cloth particle coordinates follow the renderer's root bone.
            // Keep that space equal to our proxy, while the hip skinning bone
            // drives the pinned waist. An animated hip root offsets it twice.
            skin.rootBone = proxy;
            skin.updateWhenOffscreen = true;
            skin.shadowCastingMode = ShadowCastingMode.Off;
            simulationMaterial = new Material(Shader.Find("Unlit/Color"));
            skin.sharedMaterial = simulationMaterial;
            // Layer 31 is excluded by every camera. Simulation stays enabled.
            cloth = go.AddComponent<Cloth>();
            // Cloth may reorder or merge mesh vertices. Our cage has no UV
            // seam duplicates, but never assume PhysX keeps the input order.
            var initialParticles = cloth.vertices;
            if (initialParticles.Length != vertices.Length)
                throw new InvalidOperationException("Cloth changed the unique cage vertex count");
            particleToControl = new int[vertices.Length];
            var assigned = new bool[vertices.Length];
            for (int p = 0; p < initialParticles.Length; p++)
            {
                int closest = -1; float distance = float.PositiveInfinity;
                for (int v = 0; v < vertices.Length; v++)
                {
                    float d = (initialParticles[p] - vertices[v]).sqrMagnitude;
                    if (!assigned[v] && d < distance) { distance = d; closest = v; }
                }
                if (closest < 0 || distance > 0.000004f)
                    throw new InvalidOperationException("Cloth rest-space correspondence exceeds 2 mm");
                particleToControl[p] = closest; assigned[closest] = true;
            }
            cloth.useGravity = true; cloth.damping = 0.65f;
            cloth.stretchingStiffness = 1; cloth.bendingStiffness = 0.85f;
            cloth.friction = 0.5f; cloth.collisionMassScale = 3;
            cloth.clothSolverFrequency = 120;
            cloth.enableContinuousCollision = true;
            var coefficients = new ClothSkinningCoefficient[vertices.Length];
            for (int i = 0; i < coefficients.Length; i++)
            {
                float row = (float)(particleToControl[i] / data.segments) / (data.rows - 1);
                // Physics adds folds around a pose-corrected skirt silhouette.
                // 65 cm of freedom on a 40 cm skirt allowed it to invert fully.
                coefficients[i] = new ClothSkinningCoefficient { maxDistance = row * 0.045f, collisionSphereDistance = 0 };
            }
            cloth.coefficients = coefficients;
            var colliders = new CapsuleCollider[4];
            int[] from = { 11, 15, 12, 16 }, to = { 12, 16, 13, 17 };
            for (int i = 0; i < 4; i++)
            {
                var anchor = new GameObject("Cloth leg collision");
                anchor.transform.SetParent(actor.Bones[from[i]], false);
                Vector3 delta = anchor.transform.InverseTransformPoint(actor.Bones[to[i]].position);
                anchor.transform.localRotation = Quaternion.FromToRotation(Vector3.up, delta.normalized);
                var capsule = anchor.AddComponent<CapsuleCollider>();
                capsule.direction = 1;
                capsule.radius = data.capsuleRadii[i] + 0.012f;
                capsule.height = delta.magnitude + 2 * capsule.radius;
                capsule.center = Vector3.up * delta.magnitude / 2;
                capsule.isTrigger = true;
                colliders[i] = capsule;
            }
            cloth.capsuleColliders = colliders;
            cloth.useVirtualParticles = 1;
            cloth.selfCollisionDistance = 0.012f; cloth.selfCollisionStiffness = 0.85f;
            var self = new System.Collections.Generic.List<uint>();
            for (uint p = 0; p < controls.Length; p++)
                if (particleToControl[p] >= data.segments) self.Add(p);
            cloth.SetSelfAndInterCollisionIndices(self);
        }

        public void UpdateGuide()
        {
            if (guides == null) return;
            Vector3 hanging = Vector3.Slerp(anchorHip.TransformDirection(down), Vector3.down, 0.75f).normalized;
            Quaternion gravityFrame = Quaternion.FromToRotation(anchorHip.TransformDirection(down), hanging);
            for (int col = 0; col < guides.Length; col++)
            {
                float lift = 0;
                foreach (int leg in Thighs)
                {
                    Vector3 axis = (actor.Bones[leg + 1].position - actor.Bones[leg].position).normalized;
                    float angle = Mathf.Max(0, Vector3.Angle(hanging, axis) - 12);
                    var planar = Vector3.ProjectOnPlane(axis, hanging).normalized;
                    Vector3 worldRadial = gravityFrame * anchorHip.TransformDirection(radial[col]);
                    float alignment = Mathf.Clamp01((Vector3.Dot(worldRadial, planar) + 0.30f) / 1.30f);
                    // Broad lift across several pleats, rather than a sharp
                    // one-column spike at the knee. Capture twist remains intact.
                    lift = Mathf.Max(lift, Mathf.Min(100, angle * 1.10f) * Mathf.SmoothStep(0, 1, alignment));
                }
                lifts[col] = lift;
            }
            for (int col = 0; col < guides.Length; col++)
                smoothed[col] = (lifts[(col + guides.Length - 1) % guides.Length] + 2 * lifts[col] + lifts[(col + 1) % guides.Length]) * 0.25f;
            for (int col = 0; col < guides.Length; col++)
            {
                Vector3 worldRadial = gravityFrame * anchorHip.TransformDirection(radial[col]);
                guides[col].rotation = Quaternion.AngleAxis(smoothed[col], Vector3.Cross(hanging, worldRadial).normalized) * gravityFrame * anchorHip.rotation;
            }
        }

        public void Draw()
        {
            if (cloth == null) return;
            var vertices = cloth.vertices;
            if (vertices.Length != controls.Length) return;
            MaximumDisplacement = 0;
            MaximumAnchorError = 0;
            for (int i = 0; i < controls.Length; i++)
            {
                int index = particleToControl[i];
                Vector3 guide = guides[index % anchorCount].TransformPoint(restInGuide[index]);
                Vector3 world = proxy.TransformPoint(vertices[i]);
                if (!float.IsFinite(world.sqrMagnitude)) continue;
                // Keep deterministic waist attachment and a bounded secondary
                // displacement if physics is one frame behind a fast kick/seek.
                float row = (float)(index / anchorCount) / (rows - 1);
                world = guide + Vector3.ClampMagnitude(world - guide, row * 0.045f);
                Transform control = controls[index];
                if (index < anchorCount)
                    MaximumAnchorError = Mathf.Max(MaximumAnchorError,
                        Vector3.Distance(world, anchorHip.TransformPoint(restInHip[particleToControl[i]])));
                MaximumDisplacement = Mathf.Max(MaximumDisplacement, Vector3.Distance(control.position, world));
                control.position = world;
            }
            if (++drawnFrames == 60)
                Debug.Log($"DOLLFIGHT_CLOTH anchorError={MaximumAnchorError:0.0000} particle0={vertices[0]} hip={anchorHip.position}");
        }

        public void ResetSimulation()
        {
            if (cloth != null) { cloth.enabled = false; cloth.enabled = true; cloth.ClearTransformMotion(); }
        }

        void OnDestroy()
        {
            if (simulationMesh != null) Destroy(simulationMesh);
            if (simulationMaterial != null) Destroy(simulationMaterial);
        }
    }
}
