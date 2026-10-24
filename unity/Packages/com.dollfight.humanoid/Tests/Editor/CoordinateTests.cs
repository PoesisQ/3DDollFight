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
    }
}
