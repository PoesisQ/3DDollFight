using NUnit.Framework;
using UnityEngine;

namespace DollFight.Tests
{
    public sealed class CoordinateTests
    {
        [Test]
        public void BasisConversionCommutesWithArbitraryRotation()
        {
            var source = Quaternion.Euler(35, -172, 91);
            var point = new Vector3(0.4f, 1.3f, -0.7f);
            var a = HumanoidReplay.StageToUnity(source * point);
            var b = HumanoidReplay.StageToUnity(source) * HumanoidReplay.StageToUnity(point);
            Assert.Less(Vector3.Distance(a, b), 1e-5f);
        }

        [Test]
        public void WrongCoordinateContractFailsBeforeBinding()
        {
            Assert.Throws<System.ArgumentException>(() => HumanoidReplay.ValidateClip(new MotionClip()));
            Assert.AreEqual(19, HumanoidReplay.BoneOrder.Length);
        }

        [Test]
        public void Vrm10ImportUsesXReflection()
        {
            // The generic glTF Z conversion also passes the commutation test,
            // but does not match UniVRM 1.0's imported bind skeleton.
            Assert.AreEqual(new Vector3(-0.3f, 1, 0.2f),
                HumanoidReplay.StageToUnity(new Vector3(0.3f, 1, 0.2f)));
            var forward = HumanoidReplay.StageToUnity(Quaternion.AngleAxis(90, Vector3.up)) * Vector3.forward;
            Assert.Less(Vector3.Distance(forward, Vector3.left), 1e-5f);
        }

        [Test]
        public void AvatarScaleDoesNotChangeArenaTravel()
        {
            var position = HumanoidReplay.MapRoot(new Vector3(0.6f, 0.8f, -0.4f), 1, 0.9f, 1.2f);
            Assert.Less(Vector3.Distance(position, new Vector3(-0.6f, 0.66f, -0.4f)), 1e-6f);
        }

        [Test]
        public void TeamAvatarIsHumanoidAndItsPreparedBindIsATPose()
        {
            var prefab = UnityEditor.AssetDatabase.LoadAssetAtPath<GameObject>("Assets/Resources/TeamCharacter.prefab");
            Assert.IsNotNull(prefab);
            var animator = prefab.GetComponent<Animator>();
            Assert.IsTrue(animator.avatar.isValid && animator.avatar.isHuman);
            foreach (var id in HumanoidReplay.BoneOrder) Assert.IsNotNull(animator.GetBoneTransform(id), id.ToString());
            Vector3 left = animator.GetBoneTransform(HumanBodyBones.LeftHand).position - animator.GetBoneTransform(HumanBodyBones.LeftUpperArm).position;
            Assert.Greater(Vector3.Dot(left.normalized, Vector3.left), 0.97f);
            Vector3 toe = animator.GetBoneTransform(HumanBodyBones.LeftToes).position - animator.GetBoneTransform(HumanBodyBones.LeftFoot).position;
            Assert.Greater(toe.z, 0);
            Assert.IsNotNull(animator.GetBoneTransform(HumanBodyBones.LeftIndexDistal));
            Assert.IsNotNull(animator.GetBoneTransform(HumanBodyBones.RightLittleDistal));
        }

        [Test]
        public void LimbIKKeepsBoneLengthsAndEndOrientation()
        {
            var root = new GameObject("test chain");
            var middle = new GameObject("middle").transform;
            var end = new GameObject("end").transform;
            try
            {
                middle.SetParent(root.transform); middle.localPosition = new Vector3(0, -0.3f, 0.1f);
                end.SetParent(middle); end.localPosition = new Vector3(0, -0.3f, -0.1f);
                root.transform.rotation = Quaternion.Euler(0, 125, 0);
                Quaternion orientation = end.rotation;
                float length = middle.localPosition.magnitude;
                Vector3 target = root.transform.TransformPoint(new Vector3(0.10f, -0.52f, 0.12f));
                HumanoidLimbIK.Solve(root.transform, middle, end, target);
                Assert.Less(Vector3.Distance(end.position, target), 1e-5f);
                Assert.AreEqual(length, Vector3.Distance(root.transform.position, middle.position), 1e-5f);
                Assert.AreEqual(length, Vector3.Distance(middle.position, end.position), 1e-5f);
                Assert.Less(Quaternion.Angle(orientation, end.rotation), 0.01f);
            }
            finally { Object.DestroyImmediate(root); }
        }
    }
}
