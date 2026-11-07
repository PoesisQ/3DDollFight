using System.IO;
using System.Linq;
using NUnit.Framework;
using UnityEditor;
using UnityEngine;

namespace DollFight.Tests
{
    public sealed class TripoCharacterTests
    {
        const string PrefabPath = "Assets/Resources/DollFight/Characters/TripoB9E9.prefab";

        [Test]
        public void PreparedPrefabHasAllReplayBonesInMeterScaleTPose()
        {
            var prefab = AssetDatabase.LoadAssetAtPath<GameObject>(PrefabPath);
            Assert.That(prefab, Is.Not.Null, "Run DollFight.Editor.TripoCharacterImport.Prepare first.");
            var instance = Object.Instantiate(prefab);
            try
            {
                var animator = instance.GetComponent<Animator>();
                Assert.That(animator, Is.Not.Null);
                Assert.That(animator.avatar, Is.Not.Null);
                Assert.That(animator.avatar.isHuman && animator.avatar.isValid, Is.True);
                Assert.That(animator.enabled, Is.False, "Replay owns bone transforms.");
                foreach (var bone in HumanoidReplay.BoneOrder)
                    Assert.That(animator.GetBoneTransform(bone), Is.Not.Null, bone.ToString());
                Assert.That(animator.GetBoneTransform(HumanBodyBones.Head).position.y,
                    Is.EqualTo(1.48f).Within(.015f));
                Assert.That(Vector3.Dot(instance.transform.forward, Vector3.forward), Is.GreaterThan(.999f));
                foreach (var side in new[] { HumanBodyBones.LeftUpperArm, HumanBodyBones.RightUpperArm })
                {
                    var upper = animator.GetBoneTransform(side);
                    var hand = animator.GetBoneTransform(side == HumanBodyBones.LeftUpperArm
                        ? HumanBodyBones.LeftHand : HumanBodyBones.RightHand);
                    var direction = (hand.position - upper.position).normalized;
                    Assert.That(Mathf.Abs(direction.y), Is.LessThan(.08f), side + " must be horizontal");
                    Assert.That(Mathf.Abs(direction.z), Is.LessThan(.08f), side + " must lie in the T-pose plane");
                    Assert.That(direction.x * (side == HumanBodyBones.LeftUpperArm ? -1 : 1),
                        Is.GreaterThan(.98f), side + " must match +Z-facing humanoid laterality");
                }
                foreach (var side in new[] { HumanBodyBones.LeftFoot, HumanBodyBones.RightFoot })
                {
                    var toe = animator.GetBoneTransform(side == HumanBodyBones.LeftFoot
                        ? HumanBodyBones.LeftToes : HumanBodyBones.RightToes);
                    Assert.That(toe.position.z - animator.GetBoneTransform(side).position.z,
                        Is.GreaterThan(.01f), side + " toes face +Z");
                }
            }
            finally { Object.DestroyImmediate(instance); }
        }

        [Test]
        public void PreparedPrefabUsesSuppliedAlbedoNormalAndPackedMetallicSmoothness()
        {
            var prefab = AssetDatabase.LoadAssetAtPath<GameObject>(PrefabPath);
            Assert.That(prefab, Is.Not.Null);
            var skins = prefab.GetComponentsInChildren<SkinnedMeshRenderer>();
            Assert.That(skins.Length, Is.GreaterThan(0));
            Assert.That(skins.Sum(s => s.sharedMesh.triangles.Length / 3), Is.GreaterThan(1000));
            foreach (var material in skins.SelectMany(s => s.sharedMaterials))
            {
                Assert.That(material, Is.Not.Null);
                Assert.That(material.shader.name, Is.EqualTo("Standard"));
                foreach (string property in new[] { "_MainTex", "_BumpMap", "_MetallicGlossMap" })
                    Assert.That(material.GetTexture(property), Is.Not.Null, property);
                Assert.That(material.IsKeywordEnabled("_NORMALMAP"), Is.True);
                Assert.That(material.IsKeywordEnabled("_METALLICGLOSSMAP"), Is.True);
            }
        }

        [Test]
        public void PreparedPrefabReplaysRealMotionWithSoleContactAndFiniteSkinnedGeometry()
        {
            var prefab = AssetDatabase.LoadAssetAtPath<GameObject>(PrefabPath);
            Assert.That(prefab, Is.Not.Null);
            var owner = new GameObject("Tripo replay regression");
            try
            {
                var body = Object.Instantiate(prefab, owner.transform);
                var replay = owner.AddComponent<HumanoidReplay>();
                replay.externallyDriven = true;
                replay.existingHumanoid = body.GetComponent<Animator>();
                string motion = Path.Combine(Application.streamingAssetsPath, "DollFight/player-1-motion.json");
                Assert.That(File.Exists(motion), Is.True, "Regression requires the supplied real replay.");
                // existingHumanoid takes the synchronous binding path; this
                // exercises actual weighted shoe sampling and replay/IK.
                replay.LoadAsync(null, File.ReadAllText(motion)).GetAwaiter().GetResult();
                Assert.That(replay.Ready, Is.True);
                for (int sample = 0; sample <= 12; sample++)
                {
                    replay.Apply(replay.Duration * sample / 12);
                    foreach (var bone in replay.Bones)
                    {
                        Assert.That(float.IsNaN(bone.position.sqrMagnitude) || float.IsInfinity(bone.position.sqrMagnitude), Is.False);
                        Assert.That(Vector3.Distance(bone.position, replay.Bones[0].position), Is.LessThan(3));
                        float rotationNorm = Quaternion.Dot(bone.rotation, bone.rotation);
                        Assert.That(float.IsNaN(rotationNorm) || float.IsInfinity(rotationNorm), Is.False);
                    }
                    foreach (var skin in body.GetComponentsInChildren<SkinnedMeshRenderer>())
                    {
                        var baked = new Mesh();
                        try
                        {
                            skin.BakeMesh(baked);
                            foreach (var vertex in baked.vertices)
                            {
                                Vector3 world = skin.transform.TransformPoint(vertex);
                                Assert.That(float.IsNaN(world.sqrMagnitude) || float.IsInfinity(world.sqrMagnitude), Is.False);
                                Assert.That(Vector3.Distance(world, replay.Bones[0].position), Is.LessThan(3),
                                    $"Skinned vertex escaped the body at t={replay.Duration * sample / 12:F2}");
                            }
                        }
                        finally { Object.DestroyImmediate(baked); }
                    }
                }
            }
            finally { Object.DestroyImmediate(owner); }
        }
    }
}
