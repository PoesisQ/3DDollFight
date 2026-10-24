using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Rendering;

namespace DollFight
{
    // A rendering rig copied from the evaluated world pose. No second Animator,
    // cloth, spring simulation or hitboxes. View-only arm IK keeps a raised guard
    // clear of the eye without changing what the opponent/global camera sees.
    [DefaultExecutionOrder(13000)]
    public sealed class FirstPersonBody : MonoBehaviour
    {
        readonly List<Mesh> generated = new List<Mesh>();
        readonly Dictionary<Transform, Transform> copies = new Dictionary<Transform, Transform>();
        Transform[] sourceNodes, viewNodes;
        HumanoidReplay actor;
        Camera viewCamera;
        GameObject viewRoot;
        static readonly int[] Arms = { 5, 8 };

        public void Initialize(HumanoidReplay actor, Camera camera, int worldLayer, int bodyLayer)
        {
            this.actor = actor; viewCamera = camera;
            viewRoot = new GameObject("Own view rig (pose copy only)");
            viewRoot.transform.SetParent(actor.ModelRoot.parent, false);
            copies[actor.ModelRoot] = viewRoot.transform;
            sourceNodes = actor.ModelRoot.GetComponentsInChildren<Transform>();
            viewNodes = new Transform[sourceNodes.Length];
            for (int i = 0; i < sourceNodes.Length; i++)
            {
                var node = sourceNodes[i];
                if (!copies.TryGetValue(node, out var copy))
                {
                    copy = new GameObject(node.name).transform;
                    copy.SetParent(copies[node.parent], false); copies[node] = copy;
                }
                copy.localPosition = node.localPosition; copy.localRotation = node.localRotation; copy.localScale = node.localScale;
                viewNodes[i] = copy;
            }
            var head = actor.Bones[3]; // Remove neck as well: no open neck near the eye.
            var originals = actor.ModelRoot.GetComponentsInChildren<Renderer>();
            foreach (var renderer in originals)
            {
                if (renderer.gameObject.layer == 31) continue;
                renderer.gameObject.layer = worldLayer;
                renderer.shadowCastingMode = ShadowCastingMode.On;
                if (!(renderer is SkinnedMeshRenderer skin) || skin.sharedMesh == null) continue;
                skin.updateWhenOffscreen = true;
                var source = skin.sharedMesh;
                var weights = source.boneWeights;
                if (weights.Length != source.vertexCount) continue;
                var headBones = new bool[skin.bones.Length];
                var limbBones = new bool[skin.bones.Length];
                for (int b = 0; b < headBones.Length; b++)
                {
                    headBones[b] = skin.bones[b] == head || skin.bones[b].IsChildOf(head);
                    foreach (int limb in new[] { 5, 8, 11, 15 })
                        limbBones[b] |= skin.bones[b] == actor.Bones[limb] || skin.bones[b].IsChildOf(actor.Bones[limb]);
                }
                var hidden = new bool[weights.Length];
                for (int v = 0; v < weights.Length; v++)
                {
                    var w = weights[v];
                    float h = (headBones[w.boneIndex0] ? w.weight0 : 0) +
                        (headBones[w.boneIndex1] ? w.weight1 : 0) +
                        (headBones[w.boneIndex2] ? w.weight2 : 0) +
                        (headBones[w.boneIndex3] ? w.weight3 : 0);
                    float limbWeight = (limbBones[w.boneIndex0] ? w.weight0 : 0) +
                        (limbBones[w.boneIndex1] ? w.weight1 : 0) +
                        (limbBones[w.boneIndex2] ? w.weight2 : 0) +
                        (limbBones[w.boneIndex3] ? w.weight3 : 0);
                    // No skirt/chest layer in front of the eye during a kick.
                    // Complete arms remain connected through their sleeves.
                    hidden[v] = h > 0.20f || limbWeight < 0.50f;
                }
                var mesh = Instantiate(source); mesh.name = source.name + " (headless view)";
                int visible = 0;
                for (int sub = 0; sub < source.subMeshCount; sub++)
                {
                    var input = source.GetTriangles(sub); var triangles = new List<int>(input.Length);
                    for (int t = 0; t < input.Length; t += 3)
                        if (!hidden[input[t]] && !hidden[input[t + 1]] && !hidden[input[t + 2]])
                        { triangles.Add(input[t]); triangles.Add(input[t + 1]); triangles.Add(input[t + 2]); }
                    visible += triangles.Count;
                    mesh.SetTriangles(triangles, sub, false);
                }
                if (visible == 0) { Destroy(mesh); continue; }
                generated.Add(mesh);
                var go = new GameObject(skin.name + " own body");
                go.transform.SetParent(copies[skin.transform], false); go.layer = bodyLayer;
                var view = go.AddComponent<SkinnedMeshRenderer>();
                view.sharedMesh = mesh; view.sharedMaterials = skin.sharedMaterials;
                view.bones = System.Array.ConvertAll(skin.bones, b => copies[b]);
                view.rootBone = skin.rootBone != null ? copies[skin.rootBone] : viewRoot.transform;
                view.localBounds = skin.localBounds; view.updateWhenOffscreen = true;
                view.shadowCastingMode = ShadowCastingMode.Off;
                view.receiveShadows = false;
            }
        }

        void LateUpdate()
        {
            if (sourceNodes == null || !actor.Ready || !viewCamera.enabled) return;
            for (int i = 0; i < sourceNodes.Length; i++)
            {
                viewNodes[i].localPosition = sourceNodes[i].localPosition;
                viewNodes[i].localRotation = sourceNodes[i].localRotation;
            }
            foreach (int arm in Arms)
            {
                Transform shoulder = copies[actor.Bones[arm]], elbow = copies[actor.Bones[arm + 1]], hand = copies[actor.Bones[arm + 2]];
                Vector3 local = viewCamera.transform.InverseTransformPoint(hand.position);
                float near = 1 - Mathf.SmoothStep(0, 1, (local.z - 0.35f) / 0.30f);
                // The supplied FBX has oversized shoulder armour. Place its
                // view-only shoulder behind/below the eye, as a dedicated FPS
                // rig would, rather than cutting a visible end off the sleeve.
                // Keep the source hand target: this offset never reaches the
                // world skeleton, and legs keep their unmodified pose copy.
                if (actor.existingHumanoid != null)
                    shoulder.position -= viewCamera.transform.forward * 0.16f + Vector3.up * 0.12f;
                Vector3 safe = local;
                safe.z = Mathf.Max(local.z, 0.42f);
                safe.y = Mathf.Min(local.y, -0.20f);
                float side = arm == 5 ? -1 : 1;
                safe.x = side * Mathf.Max(Mathf.Abs(local.x), 0.18f);
                Vector3 target = viewCamera.transform.TransformPoint(Vector3.Lerp(local, safe, near));
                HumanoidLimbIK.Solve(shoulder, elbow, hand, target);
            }
        }

        void OnDestroy()
        {
            foreach (var mesh in generated) if (mesh != null) Destroy(mesh);
            if (viewRoot != null) Destroy(viewRoot);
        }
    }
}
