using UnityEngine;

namespace DollFight
{
    // Display the rule engine's canonical geometry, never the view-only rig or
    // clothing. No Physics colliders are created and no pose is modified.
    public sealed class DuelCollisionOverlay : MonoBehaviour
    {
        Camera targetCamera;
        Material material;
        DuelFrame frame;
        bool visible;

        public void Initialize(Camera camera, Shader shader)
        {
            targetCamera = camera;
            material = new Material(shader) { hideFlags = HideFlags.HideAndDontSave };
        }

        public void Show(DuelFrame snapshot, bool enabled)
        {
            frame = snapshot; visible = enabled;
        }

        void OnRenderObject()
        {
            if (!visible || frame == null || material == null || Camera.current != targetCamera) return;
            Draw(frame.hurtCapsules, false);
            Draw(frame.attackCapsules, true);
        }

        void Draw(DuelCapsule[] capsules, bool attack)
        {
            if (capsules == null) return;
            foreach (var capsule in capsules)
            {
                material.color = attack ? new Color(1, 0.85f, 0.3f) : capsule.player == 0
                    ? new Color(0.45f, 1, 0.8f) : new Color(1, 0.55f, 0.45f);
                material.SetPass(0);
                GL.PushMatrix(); GL.Begin(GL.LINES);
                var a = HumanoidReplay.StageToUnity(capsule.a);
                var b = HumanoidReplay.StageToUnity(capsule.b);
                var axis = (b - a).sqrMagnitude > 0.000001f ? (b - a).normalized : Vector3.up;
                var u = Vector3.Cross(axis, Mathf.Abs(axis.y) < 0.9f ? Vector3.up : Vector3.right).normalized;
                var v = Vector3.Cross(axis, u);
                Circle(a, u, v, capsule.radius); Circle(b, u, v, capsule.radius);
                Circle(a, axis, u, capsule.radius); Circle(a, axis, v, capsule.radius);
                Circle(b, axis, u, capsule.radius); Circle(b, axis, v, capsule.radius);
                foreach (var direction in new[] { u, -u, v, -v })
                {
                    GL.Vertex(a + direction * capsule.radius);
                    GL.Vertex(b + direction * capsule.radius);
                }
                GL.End(); GL.PopMatrix();
            }
        }

        static void Circle(Vector3 center, Vector3 u, Vector3 v, float radius)
        {
            const int segments = 24;
            for (int i = 0; i < segments; i++)
            {
                float start = i * (2 * Mathf.PI / segments), end = (i + 1) * (2 * Mathf.PI / segments);
                GL.Vertex(center + radius * (Mathf.Cos(start) * u + Mathf.Sin(start) * v));
                GL.Vertex(center + radius * (Mathf.Cos(end) * u + Mathf.Sin(end) * v));
            }
        }

        void OnDestroy() { if (material != null) Destroy(material); }
    }
}
