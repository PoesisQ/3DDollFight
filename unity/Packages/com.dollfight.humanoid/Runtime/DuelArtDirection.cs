using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Rendering;

namespace DollFight
{
    /// <summary>Owns the local arena art and one-time, pose-preserving HUD portraits.</summary>
    [DefaultExecutionOrder(12500)]
    public sealed class DuelArtDirection : MonoBehaviour
    {
        static readonly Color Pink = new Color(0.953f, 0.22f, 0.616f);
        static readonly Color Cyan = new Color(0.251f, 0.812f, 1);
        readonly List<Object> owned = new List<Object>();
        readonly RenderTexture[] portraits = new RenderTexture[2];
        readonly Transform[,] shadows = new Transform[2, 2];
        readonly Material[,] shadowMaterials = new Material[2, 2];
        DollFightDemo demo;
        Transform artRoot;
        Shader surfaceShader, unlitShader;
        bool portraitCaptureStarted;

        public Texture Portrait(int player) => player >= 0 && player < portraits.Length ? portraits[player] : null;

        public void Initialize(DollFightDemo owner, Shader surface, Shader unlit)
        {
            demo = owner; surfaceShader = surface; unlitShader = unlit;
            artRoot = new GameObject("DollFight authored arena art").transform;
            artRoot.SetParent(transform, false);
            if (demo.createDefaultEnvironment) BuildUndergroundArena();
            BuildLighting();
            BuildContactShadows();
        }

        T Own<T>(T item) where T : Object { owned.Add(item); return item; }

        Material Surface(string name, Color color, float smoothness = .16f, float metallic = 0)
        {
            var material = Own(new Material(surfaceShader) { name = name, color = color });
            material.SetFloat("_Glossiness", smoothness); material.SetFloat("_Metallic", metallic);
            return material;
        }

        Material Flat(string name, Color color) => Own(new Material(unlitShader) { name = name, color = color });

        GameObject Box(string name, Vector3 position, Vector3 size, Material material)
        {
            var go = GameObject.CreatePrimitive(PrimitiveType.Cube); go.name = name;
            go.transform.SetParent(artRoot, false); go.transform.position = position; go.transform.localScale = size;
            go.GetComponent<Renderer>().sharedMaterial = material;
            // These props are presentation only. Actor and cloth collision remain unchanged.
            Destroy(go.GetComponent<Collider>());
            return go;
        }

        void Beam(string name, Vector3 a, Vector3 b, float width, Material material)
        {
            var go = Box(name, (a + b) * .5f, new Vector3(width, (b - a).magnitude, width), material);
            go.transform.rotation = Quaternion.FromToRotation(Vector3.up, b - a);
        }

        void BuildUndergroundArena()
        {
            var concrete = Surface("Worn concrete / Poly Haven CC0", new Color(.38f, .39f, .4f), .12f);
            concrete.mainTexture = Resources.Load<Texture2D>("DollFight/Textures/concrete_floor_worn_001_diff_1k");
            concrete.mainTextureScale = new Vector2(5, 4);
            var normal = Resources.Load<Texture2D>("DollFight/Textures/concrete_floor_worn_001_nor_gl_1k");
            if (normal != null) { concrete.SetTexture("_BumpMap", normal); concrete.SetFloat("_BumpScale", .58f); concrete.EnableKeyword("_NORMALMAP"); }
            Box("Worn concrete fighting floor", new Vector3(0, -.08f, 0), new Vector3(18, .16f, 14), concrete);
            var wall = Surface("Charcoal concrete", new Color(.19f, .205f, .225f), .08f);
            wall.mainTexture = concrete.mainTexture; wall.mainTextureScale = new Vector2(4.5f, 1.4f);
            if (normal != null) { wall.SetTexture("_BumpMap", normal); wall.SetFloat("_BumpScale", .35f); wall.EnableKeyword("_NORMALMAP"); }
            var metal = Surface("Blackened steel", new Color(.033f, .043f, .055f), .36f, .52f);
            var panel = Surface("Recessed blue steel panels", new Color(.057f, .075f, .094f), .26f, .28f);
            var paint = Surface("Faded ivory arena paint", new Color(.47f, .49f, .43f), .06f);
            var yellow = Surface("Safety ochre paint", new Color(.54f, .39f, .09f), .08f);
            var pink = Flat("P1 magenta light", Pink * .77f);
            var cyan = Flat("P2 cyan light", Cyan * .77f);
            var lamp = Flat("Warm overhead diffuser", new Color(.82f, .68f, .43f));
            Box("Rear concrete wall", new Vector3(0, 2.3f, -3.85f), new Vector3(16, 4.6f, .3f), wall);
            for (int i = -3; i <= 3; i++)
            {
                float x = i * 2.15f;
                Box("Inset service panel", new Vector3(x, 1.55f, -3.66f), new Vector3(1.94f, 2.65f, .055f), panel);
                Box("Vertical steel support", new Vector3(x - 1.04f, 2.25f, -3.55f), new Vector3(.11f, 4.5f, .17f), metal);
                Box("Panel lower cross member", new Vector3(x, .39f, -3.53f), new Vector3(2.05f, .09f, .12f), metal);
                if (Mathf.Abs(i) > 1)
                    Beam("Braced outer structure", new Vector3(x - .9f, .5f, -3.52f), new Vector3(x + .9f, 2.85f, -3.52f), .065f, metal);
            }
            Box("Rear structural header", new Vector3(0, 3.43f, -3.52f), new Vector3(16, .2f, .3f), metal);
            Box("Rear concrete skirting", new Vector3(0, .13f, -3.52f), new Vector3(16, .25f, .3f), metal);
            foreach (int side in new[] { -1, 1 })
            {
                var accent = side < 0 ? pink : cyan;
                Box("Low team light channel", new Vector3(side * 3.05f, .41f, -3.44f), new Vector3(3.2f, .036f, .045f), accent);
                Box("Team light upright", new Vector3(side * 4.73f, 1.72f, -3.44f), new Vector3(.045f, 2.65f, .045f), accent);
                Box("Equipment pedestal", new Vector3(side * 5.15f, .47f, -2.6f), new Vector3(.6f, .94f, .68f), metal);
                Box("Pedestal face inset", new Vector3(side * 5.15f, .6f, -2.245f), new Vector3(.43f, .24f, .018f), panel);
                Box("Overhead lamp housing", new Vector3(side * 3.5f, 3.48f, -1.8f), new Vector3(1.7f, .14f, .35f), metal);
                Box("Overhead lamp diffuser", new Vector3(side * 3.5f, 3.4f, -1.8f), new Vector3(1.48f, .018f, .24f), lamp);
                Box("Floor perimeter tape", new Vector3(side * 3.5f, .006f, -.35f), new Vector3(.055f, .008f, 4.9f), paint);
                for (int i = 0; i < 7; i++)
                {
                    var stripe = Box("Floor safety slash", new Vector3(side * 3.72f, .008f, -2.35f + i * .66f), new Vector3(.42f, .009f, .1f), yellow);
                    stripe.transform.rotation = Quaternion.Euler(0, -35, 0);
                }
            }
            GroundRing(2.25f, .025f, paint);
            Box("Floor centre stroke", new Vector3(0, .007f, 0), new Vector3(.028f, .008f, .45f), paint);
            Box("Floor centre stroke", new Vector3(0, .007f, 0), new Vector3(.45f, .008f, .028f), paint);
            var stencil = Flat("Original wall stencil", new Color(.24f, .29f, .33f));
            Lettering("Original DollFight wall identity", "DOLL / FIGHT", new Vector3(0, 2.64f, -3.47f), .052f, stencil);
            Lettering("Arena identifier", "UNDERGROUND    //    01", new Vector3(0, 2.29f, -3.46f), .012f, stencil);
        }

        void Lettering(string label, string text, Vector3 position, float size, Material material)
        {
            var go = new GameObject(label); go.transform.SetParent(artRoot, false); go.transform.position = position;
            go.transform.rotation = Quaternion.Euler(0, 180, 0);
            var mesh = go.AddComponent<TextMesh>(); mesh.text = text; mesh.anchor = TextAnchor.MiddleCenter;
            mesh.alignment = TextAlignment.Center; mesh.fontSize = 100; mesh.characterSize = size;
            mesh.color = material.color;
            var font = Resources.Load<Font>("DollFight/Fonts/BarlowCondensed-ExtraBoldItalic");
            if (font != null) { mesh.font = font; go.GetComponent<MeshRenderer>().sharedMaterial = font.material; }
        }

        void GroundRing(float radius, float thickness, Material material)
        {
            const int count = 128;
            var vertices = new Vector3[(count + 1) * 2]; var triangles = new int[count * 6];
            for (int i = 0; i <= count; i++)
            {
                float angle = i * Mathf.PI * 2 / count; var radial = new Vector3(Mathf.Cos(angle), 0, Mathf.Sin(angle));
                vertices[i * 2] = radial * (radius - thickness); vertices[i * 2 + 1] = radial * radius;
                if (i == count) continue;
                int t = i * 6, v = i * 2;
                triangles[t] = v; triangles[t + 1] = v + 2; triangles[t + 2] = v + 1;
                triangles[t + 3] = v + 1; triangles[t + 4] = v + 2; triangles[t + 5] = v + 3;
            }
            var mesh = Own(new Mesh { name = "Original arena painted circle", vertices = vertices, triangles = triangles });
            mesh.RecalculateNormals(); mesh.RecalculateBounds();
            var go = new GameObject("Faded painted fighting circle"); go.transform.SetParent(artRoot, false); go.transform.position = Vector3.up * .009f;
            go.AddComponent<MeshFilter>().sharedMesh = mesh; go.AddComponent<MeshRenderer>().sharedMaterial = material;
        }

        void BuildLighting()
        {
            bool studio = demo.createDefaultEnvironment;
            RenderSettings.ambientMode = AmbientMode.Trilight;
            RenderSettings.ambientSkyColor = studio ? new Color(.5f, .54f, .59f) : new Color(.36f, .4f, .48f);
            RenderSettings.ambientEquatorColor = studio ? new Color(.32f, .35f, .39f) : new Color(.23f, .26f, .32f);
            RenderSettings.ambientGroundColor = studio ? new Color(.2f, .21f, .23f) : new Color(.14f, .15f, .18f);
            var key = NewLight("Warm soft arena key", LightType.Directional,
                studio ? new Color(1, .96f, .9f) : new Color(1, .9f, .79f), studio ? 1.05f : .82f);
            key.transform.rotation = studio ? Quaternion.Euler(42, 155, 0) : Quaternion.Euler(48, -32, 0);
            key.shadows = LightShadows.Soft; key.shadowStrength = studio ? .38f : .65f;
            key.shadowBias = .005f; key.shadowNormalBias = .015f;
            var fill = NewLight("Cool portrait fill", LightType.Directional,
                studio ? new Color(.72f, .82f, 1) : new Color(.61f, .76f, 1), studio ? .4f : .24f);
            fill.transform.rotation = studio ? Quaternion.Euler(30, -30, 0) : Quaternion.Euler(24, 145, 0);
            var rim = NewLight("Soft rear edge light", LightType.Directional, new Color(.67f, .8f, 1), studio ? .32f : .29f);
            rim.transform.rotation = studio ? Quaternion.Euler(28, -15, 0) : Quaternion.Euler(22, 180, 0);
            if (!studio) return;
            // A low, camera-side fill opens faces beneath hair and the FBX hat.
            // It affects the characters without lifting the dark arena backdrop.
            var faceFill = NewLight("Character camera-side soft fill", LightType.Directional, new Color(.91f, .95f, 1), .42f);
            faceFill.transform.rotation = Quaternion.Euler(12, 180, 0);
            faceFill.cullingMask = (1 << 8) | (1 << 10) | (1 << 12) | (1 << 13);
            foreach (int side in new[] { -1, 1 })
            {
                var light = NewLight("Team wall wash", LightType.Point, side < 0 ? Pink : Cyan, 1.05f);
                light.transform.position = new Vector3(side * 3.8f, 1.4f, -2.6f); light.range = 4;
            }
        }

        Light NewLight(string name, LightType type, Color color, float intensity)
        {
            var light = new GameObject(name).AddComponent<Light>(); light.transform.SetParent(artRoot, false);
            light.type = type; light.color = color; light.intensity = intensity;
            light.cullingMask = ~(1 << 31); light.shadows = LightShadows.None; return light;
        }

        void BuildContactShadows()
        {
            var shader = Resources.Load<Shader>("DollFight/Shaders/ContactShadow");
            if (shader == null) return;
            var texture = Own(new Texture2D(64, 64, TextureFormat.RGBA32, false) { name = "Soft contact falloff", wrapMode = TextureWrapMode.Clamp });
            var pixels = new Color[64 * 64];
            for (int y = 0; y < 64; y++) for (int x = 0; x < 64; x++)
            {
                float r = new Vector2((x + .5f) / 32 - 1, (y + .5f) / 32 - 1).magnitude;
                pixels[y * 64 + x] = new Color(1, 1, 1, Mathf.Pow(Mathf.Clamp01(1 - r * r), 3));
            }
            texture.SetPixels(pixels); texture.Apply();
            for (int p = 0; p < 2; p++) for (int f = 0; f < 2; f++)
            {
                var material = Own(new Material(shader) { name = "Soft sole contact", mainTexture = texture, color = new Color(.018f, .022f, .033f, .32f) });
                var go = GameObject.CreatePrimitive(PrimitiveType.Quad); go.name = "Soft sole ground contact";
                go.transform.SetParent(artRoot, false); Destroy(go.GetComponent<Collider>());
                go.GetComponent<Renderer>().sharedMaterial = material; go.GetComponent<Renderer>().shadowCastingMode = ShadowCastingMode.Off;
                go.transform.rotation = Quaternion.Euler(90, 0, 0); go.SetActive(false);
                shadows[p, f] = go.transform; shadowMaterials[p, f] = material;
            }
        }

        void LateUpdate()
        {
            if (demo == null || !demo.Ready) return;
            for (int p = 0; p < 2; p++) for (int f = 0; f < 2; f++)
            {
                var shadow = shadows[p, f]; if (shadow == null) continue;
                var foot = demo.Actors[p].Bones[f == 0 ? 13 : 17];
                float height = Mathf.Max(0, foot.position.y - .07f);
                float strength = Mathf.Clamp01(1 - height / .55f);
                shadow.gameObject.SetActive(strength > .01f);
                shadow.position = new Vector3(foot.position.x, .012f, foot.position.z);
                shadow.localScale = new Vector3(.44f + height * .2f, .3f + height * .2f, 1);
                shadowMaterials[p, f].color = new Color(.018f, .022f, .033f, .34f * strength * strength);
            }
        }

        public void CapturePortraits()
        {
            if (portraitCaptureStarted) return;
            portraitCaptureStarted = true; StartCoroutine(CaptureAfterPose());
        }

        IEnumerator CaptureAfterPose()
        {
            // Capture the evaluated world pose, never a temporary bind/portrait pose.
            yield return new WaitForEndOfFrame();
            if (demo == null || !demo.Ready) yield break;
            var cameraObject = new GameObject("One-time local portrait camera");
            var camera = cameraObject.AddComponent<Camera>(); camera.enabled = false;
            var portraitLight = cameraObject.AddComponent<Light>();
            portraitLight.type = LightType.Directional; portraitLight.color = new Color(1, .97f, .93f);
            portraitLight.intensity = .7f; portraitLight.shadows = LightShadows.None;
            camera.cameraType = CameraType.Preview; camera.clearFlags = CameraClearFlags.SolidColor;
            camera.backgroundColor = Color.clear; camera.nearClipPlane = .035f; camera.farClipPlane = 4;
            camera.allowHDR = false; camera.allowMSAA = true; camera.fieldOfView = 34;
            var previousActive = RenderTexture.active;
            try
            {
                for (int p = 0; p < 2; p++)
                {
                    var actor = demo.Actors[p]; var head = actor.Bones[4].position;
                    Vector3 facing = demo.Actors[1 - p].Bones[0].position - actor.Bones[0].position;
                    facing.y = 0; facing.Normalize(); if (facing.sqrMagnitude < .5f) facing = p == 0 ? Vector3.left : Vector3.right;
                    Vector3 side = Vector3.Cross(Vector3.up, facing);
                    Vector3 target = head - Vector3.up * .03f;
                    // Face/shoulder crops deliberately let the broad hat leave frame.
                    camera.fieldOfView = 34;
                    float distance = 1.07f;
                    camera.transform.position = target + facing * distance + side * .19f + Vector3.up * .015f;
                    camera.transform.LookAt(target); camera.aspect = .8f;
                    // Native Gaussian rendering respects these masks; Preview additionally skips its callbacks.
                    camera.cullingMask = (1 << (8 + p * 2)) | (1 << (12 + p));
                    portraitLight.cullingMask = camera.cullingMask;
                    portraits[p] = new RenderTexture(320, 400, 24, RenderTextureFormat.ARGB32)
                    { name = "P" + (p + 1) + " transparent portrait", antiAliasing = 4 };
                    portraits[p].Create(); camera.targetTexture = portraits[p]; camera.Render(); camera.targetTexture = null;
                }
            }
            finally { camera.targetTexture = null; RenderTexture.active = previousActive; Destroy(cameraObject); }
        }

        void OnDestroy()
        {
            StopAllCoroutines();
            foreach (var portrait in portraits) if (portrait != null) { portrait.Release(); Destroy(portrait); }
            foreach (var item in owned) if (item != null) Destroy(item);
            if (artRoot != null) Destroy(artRoot.gameObject);
        }
    }
}
