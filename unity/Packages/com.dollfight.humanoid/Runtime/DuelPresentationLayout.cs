using UnityEngine;

namespace DollFight
{
    /// <summary>All rectangles use GUI pixels (top left origin), until CameraRect converts them.</summary>
    public static class DuelPresentationLayout
    {
        public const float ArenaAspect = 16f / 9f;
        public static float ToolbarHeight(float width) => 52 * Mathf.Clamp(width / 1440f, 0.7f, 1.3f);
        public static Rect Arena(float width, float height)
        {
            float available = Mathf.Max(1, height - ToolbarHeight(width));
            float w = Mathf.Min(Mathf.Max(1, width), available * ArenaAspect);
            float h = w / ArenaAspect;
            return new Rect((width - w) * 0.5f, (available - h) * 0.5f, w, h);
        }
        public static Rect PlayerView(Rect arena, int player)
        {
            float margin = arena.width * 0.018f;
            float w = arena.width * 0.225f, h = w / ArenaAspect;
            return new Rect(player == 0 ? arena.x + margin : arena.xMax - margin - w,
                arena.yMax - margin - h, w, h);
        }
        public static Rect CameraRect(Rect pixels, float width, float height) =>
            new Rect(pixels.x / width, 1 - pixels.yMax / height, pixels.width / width, pixels.height / height);
        public static void Apply(Camera camera, Rect pixels, float width, float height)
        {
            camera.rect = CameraRect(pixels, width, height);
            camera.aspect = pixels.width / Mathf.Max(1, pixels.height);
            camera.ResetProjectionMatrix();
        }
    }
}
