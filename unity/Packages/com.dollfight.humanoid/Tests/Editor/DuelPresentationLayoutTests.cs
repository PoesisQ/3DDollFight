using NUnit.Framework;
using UnityEngine;

namespace DollFight.Tests
{
    public sealed class DuelPresentationLayoutTests
    {
        [TestCase(1440, 900)]
        [TestCase(960, 640)]
        [TestCase(640, 480)]
        [TestCase(2560, 1080)]
        [TestCase(720, 1100)]
        public void ArenaFitsWithoutDistortionAndReservesControls(int width, int height)
        {
            Rect arena = DuelPresentationLayout.Arena(width, height);
            Assert.That(arena.width / arena.height, Is.EqualTo(16f / 9).Within(.00001f));
            Assert.That(arena.xMin, Is.GreaterThanOrEqualTo(-.001f));
            Assert.That(arena.yMin, Is.GreaterThanOrEqualTo(-.001f));
            Assert.That(arena.xMax, Is.LessThanOrEqualTo(width + .001f));
            Assert.That(arena.yMax, Is.LessThanOrEqualTo(height - DuelPresentationLayout.ToolbarHeight(width) + .001f));
            Rect a = DuelPresentationLayout.PlayerView(arena, 0), b = DuelPresentationLayout.PlayerView(arena, 1);
            Assert.That(a.width / a.height, Is.EqualTo(16f / 9).Within(.00001f));
            Assert.That(a.xMin, Is.GreaterThan(arena.xMin));
            Assert.That(b.xMax, Is.LessThan(arena.xMax));
            Assert.That(a.yMax, Is.LessThan(arena.yMax));
            Assert.IsFalse(a.Overlaps(b));
            Assert.That(a.width, Is.LessThan(arena.width * .25f));
        }
        [Test]
        public void CameraUsesItsPixelViewportAndClearsCustomProjection()
        {
            var owner = new GameObject("layout-camera");
            try
            {
                var camera = owner.AddComponent<Camera>();
                Rect pixels = new Rect(80, 140, 640, 360);
                camera.projectionMatrix = Matrix4x4.identity;
                DuelPresentationLayout.Apply(camera, pixels, 960, 640);
                Assert.That(camera.aspect, Is.EqualTo(16f / 9).Within(.00001f));
                Assert.That(camera.rect.x, Is.EqualTo(80f / 960).Within(.00001f));
                Assert.That(camera.rect.y, Is.EqualTo(140f / 640).Within(.00001f));
                Assert.That(camera.projectionMatrix, Is.Not.EqualTo(Matrix4x4.identity));
            }
            finally { Object.DestroyImmediate(owner); }
        }
    }
}
