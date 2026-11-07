using NUnit.Framework;
using UnityEngine;

namespace DollFight.Tests
{
    public sealed class DuelHudSidesTests
    {
        // Actor identity is fixed in stage space. The two authored arena cameras
        // see that same pair from opposite sides; these use actual projection.
        static readonly Vector3 P1 = new Vector3(.8f, 1, 0);
        static readonly Vector3 P2 = new Vector3(-.8f, 1, 0);

        [TestCase(4, 0, 1)]
        [TestCase(-4, 1, 0)]
        public void MainCameraProjectionPlacesCorrectPlayerOnEachHudSide(float cameraZ, int leftPlayer, int rightPlayer)
        {
            var owner = new GameObject("HUD side camera");
            try
            {
                var camera = owner.AddComponent<Camera>();
                camera.transform.position = new Vector3(0, 1.6f, cameraZ);
                camera.transform.LookAt(new Vector3(0, 1, 0));
                camera.aspect = 16f / 9;
                var sides = new DuelHudSides();
                sides.Refresh(camera, P1, P2);
                Assert.That(sides.PlayerAtSide(0), Is.EqualTo(leftPlayer));
                Assert.That(sides.PlayerAtSide(1), Is.EqualTo(rightPlayer));
                Assert.That(sides.SideOfPlayer(leftPlayer), Is.EqualTo(0));
                Assert.That(sides.SideOfPlayer(rightPlayer), Is.EqualTo(1));
            }
            finally { Object.DestroyImmediate(owner); }
        }

        [Test]
        public void CrossingMotionDoesNotSwapIdentityBarsButCameraReversalRefreshesThem()
        {
            var owner = new GameObject("HUD stable camera");
            try
            {
                var camera = owner.AddComponent<Camera>();
                camera.transform.position = new Vector3(0, 1.6f, 4);
                camera.transform.LookAt(new Vector3(0, 1, 0));
                var sides = new DuelHudSides();
                sides.Refresh(camera, P1, P2);
                sides.Refresh(camera, P2, P1);
                Assert.That(sides.PlayerAtSide(0), Is.EqualTo(0), "Transient crossed motion must not flicker the rails or camera windows.");
                camera.transform.position = new Vector3(0, 1.6f, -4);
                camera.transform.LookAt(new Vector3(0, 1, 0));
                sides.Refresh(camera, P1, P2);
                Assert.That(sides.PlayerAtSide(0), Is.EqualTo(1));
                Assert.That(sides.SideOfPlayer(0), Is.EqualTo(1));
            }
            finally { Object.DestroyImmediate(owner); }
        }

        [Test]
        public void MissingOrOverlappingInitialProjectionDoesNotLockTheDefaultOrder()
        {
            var owner = new GameObject("HUD delayed camera");
            try
            {
                var camera = owner.AddComponent<Camera>();
                camera.transform.position = new Vector3(0, 1.6f, -4);
                camera.transform.LookAt(new Vector3(0, 1, 0));
                var sides = new DuelHudSides();
                sides.Refresh(null, P1, P2);
                sides.Refresh(camera, P1, P1);
                sides.Refresh(camera, P1, P2);
                Assert.That(sides.PlayerAtSide(0), Is.EqualTo(1));
            }
            finally { Object.DestroyImmediate(owner); }
        }
    }
}
