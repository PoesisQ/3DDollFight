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
        Vector2 shoulderOffset;
        static readonly int[] Arms = { 5, 8 };

        public void Initialize(HumanoidReplay actor, Camera camera, int worldLayer, int bodyLayer, Vector2 firstPersonShoulderOffset = default)
        {
            this.actor = actor; viewCamera = camera; shoulderOffset = firstPersonShoulderOffset;
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

        /// <summary>
        /// How close a hand may get to the eye before the rig eases it out.
        ///
        /// Nothing else about the arm is touched, on purpose. The player view is
        /// a copy of the pose, so the two views have to agree about what the arm
        /// is doing; the moment this rig starts steering, the same punch reads
        /// as two different moves.
        ///
        /// It used to steer a lot: every hand nearer than 65 cm was faded into a
        /// fixed point 42 cm ahead of the eye, 20 cm down and 18 cm to the side.
        /// Measured on the recorded sparring clip (1692 frames), that pinned the
        /// hand to that point in 1628 of them - 96 % - and the right hand's own
        /// travel dropped from 33.7 m to 17.7 m over the clip. On screen the
        /// gloves then sat still at the bottom corners while the world camera
        /// showed the punch. The fixed point was the whole reason the two views
        /// disagreed.
        /// </summary>
        const float NearField = 0.16f;

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
                // Character-specific view-only offset; world pose and hand target stay intact.
                shoulder.position -= viewCamera.transform.forward * shoulderOffset.x + Vector3.up * shoulderOffset.y;
                // Only a hand that is about to be cut by the near plane is moved,
                // and it is moved along the ray it already lies on: the arm keeps
                // pointing where the pose puts it, and a glove crossing the eye
                // slides past instead of being sliced open. A hand behind the eye
                // is not in front of the near plane at all, so it is left alone.
                float distance = local.magnitude;
                if (local.z <= 0f || distance >= NearField || distance < 0.0001f) continue;
                Vector3 target = viewCamera.transform.TransformPoint(local * (NearField / distance));
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
