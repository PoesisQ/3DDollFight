using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Threading.Tasks;
using UnityEngine;
using UnityEngine.Rendering;

namespace DollFight
{
    /// <summary>Selection-only actors. Never re-poses, relayers or changes combat actors or their materials.</summary>
    public sealed class SelectionPortraits : MonoBehaviour
    {
        const int PortraitLayer = 31;
        readonly Dictionary<string, RenderTexture[]> images = new Dictionary<string, RenderTexture[]>(StringComparer.Ordinal);
        readonly Dictionary<string, RenderTexture> rosterImages = new Dictionary<string, RenderTexture>(StringComparer.Ordinal);
        readonly List<Material> materials = new List<Material>();
        GameObject loadingActor;
        bool started, disposed;
        public bool Ready { get; private set; }
        public int LoadedCount => images.Count;
        public string Error { get; private set; }

        public Texture Get(string id, int side = 0) => id != null && images.TryGetValue(id, out var pair) ? pair[Mathf.Clamp(side, 0, 1)] : null;
        public Texture GetRoster(string id) => id != null && rosterImages.TryGetValue(id, out var image) ? image : null;

        public void Begin(CharacterCatalog catalog)
        {
            if (started) return;
            started = true; StartCoroutine(LoadAll(catalog));
        }

        IEnumerator LoadAll(CharacterCatalog catalog)
        {
            string root = Path.Combine(Application.streamingAssetsPath, "DollFight");
            string motion;
            try { motion = File.ReadAllText(Path.Combine(root, "player-1-motion.json")); }
            catch (Exception error) { Error = error.Message; Debug.LogException(error, this); yield break; }
            foreach (var definition in catalog.Characters)
            {
                var task = CreateActor(definition, root, motion);
                while (!task.IsCompleted) yield return null;
                if (disposed) yield break;
                if (task.IsCanceled) yield break;
                if (task.IsFaulted)
                {
                    Error = task.Exception.GetBaseException().Message;
                    Debug.LogException(task.Exception.GetBaseException(), this);
                    if (loadingActor != null) Destroy(loadingActor);
                    loadingActor = null; continue;
                }
                var actor = task.Result;
                // Let skinning see the evaluated fighting pose before the isolated render.
                yield return new WaitForEndOfFrame();
                if (disposed || actor == null) yield break;
                try { Capture(definition.id, actor); }
                catch (Exception error) { Error = error.Message; Debug.LogException(error, this); }
                Destroy(loadingActor); loadingActor = null;
                foreach (var material in materials) if (material != null) Destroy(material);
                materials.Clear();
                yield return null;
            }
            Ready = images.Count == catalog.Characters.Count;
        }

        async Task<HumanoidReplay> CreateActor(CharacterDefinition definition, string root, string motion)
        {
            loadingActor = new GameObject("Selection portrait / " + definition.id);
            loadingActor.transform.SetParent(transform, false);
            // Hidden from every gameplay view, even while an asynchronous VRM is importing.
            loadingActor.transform.position = new Vector3(1000, 0, 0);
            var actor = loadingActor.AddComponent<HumanoidReplay>();
            actor.externallyDriven = true; actor.playing = false;
            if (definition.modelKind == "prefab")
            {
                var prefab = Resources.Load<GameObject>(definition.resourcePath);
                if (prefab == null) throw new FileNotFoundException("Missing selection model: " + definition.id);
                var model = Instantiate(prefab, loadingActor.transform);
                actor.existingHumanoid = model.GetComponent<Animator>();
            }
            await actor.LoadAsync(definition.modelKind == "vrm" ? Path.Combine(root, definition.modelFile) : null, motion);
            if (disposed || actor == null) return null;
            foreach (Transform node in loadingActor.GetComponentsInChildren<Transform>(true)) node.gameObject.layer = PortraitLayer;
            foreach (var renderer in loadingActor.GetComponentsInChildren<Renderer>(true))
            {
                renderer.shadowCastingMode = ShadowCastingMode.Off;
                renderer.receiveShadows = false;
                if (renderer is SkinnedMeshRenderer skin) skin.updateWhenOffscreen = true;
                // Native prefab materials belong to gameplay as well. All studio changes use clones.
                var clones = renderer.materials;
                foreach (var material in clones)
                {
                    materials.Add(material);
                    string name = material.name;
                    if (material.shader != null && material.shader.name == "UniGLTF/UniUnlit" &&
                        (name.Contains("SKIN") || name.Contains("cel skin") || name.StartsWith("tripo_material") || name.StartsWith("AuthoredHair")))
                    {
                        var shader = Shader.Find("Standard");
                        if (shader != null)
                        {
                            Texture texture = material.mainTexture; Color color = material.color;
                            material.shader = shader; material.mainTexture = texture; material.color = color;
                            material.SetFloat("_Glossiness", .22f); material.SetFloat("_Metallic", 0);
                        }
                    }
                }
            }
            actor.Apply(0); actor.ProcessSecondary();
            return actor;
        }

        void Capture(string id, HumanoidReplay actor)
        {
            var go = new GameObject("Selection studio capture");
            var camera = go.AddComponent<Camera>(); camera.enabled = false;
            camera.cameraType = CameraType.Preview; camera.clearFlags = CameraClearFlags.SolidColor;
            camera.backgroundColor = Color.clear; camera.cullingMask = 1 << PortraitLayer;
            camera.nearClipPlane = .02f; camera.farClipPlane = 15;
            camera.allowHDR = false; camera.allowMSAA = true; camera.orthographic = true;
            var lights = new[] {
                AddLight(go.transform, "Warm studio key", new Color(1, .93f, .88f), 1.05f, new Vector3(28, 55, 0)),
                AddLight(go.transform, "Cool studio fill", new Color(.64f, .77f, 1), .65f, new Vector3(18, -100, 0)),
                AddLight(go.transform, "Violet studio rim", new Color(.78f, .55f, 1), .5f, new Vector3(30, 170, 0))
            };
            var oldActive = RenderTexture.active;
            var oldMode = RenderSettings.ambientMode; var oldAmbient = RenderSettings.ambientLight;
            try
            {
                RenderSettings.ambientMode = AmbientMode.Flat; RenderSettings.ambientLight = new Color(.45f, .46f, .52f);
                Vector3 hip = actor.Bones[0].position, head = actor.Bones[4].position;
                float floor = Mathf.Min(actor.Bones[13].position.y, actor.Bones[17].position.y);
                float height = Mathf.Max(.8f, head.y - floor);
                float bottom = hip.y - height * .38f;
                // SkinnedMeshRenderer.bounds can retain the imported animation envelope. Use the
                // evaluated four-weight world-space vertices, just like the native sole probe.
                var silhouette = UpperBodyVertices(actor.ModelRoot, bottom);
                if (silhouette.Count == 0) throw new InvalidOperationException("Portrait model has no upper-body surface: " + id);
                float top = head.y;
                foreach (var point in silhouette) top = Mathf.Max(top, point.y);
                Vector3 target = Vector3.Lerp(hip, head, .36f); target.y = (top + bottom) * .5f;
                camera.aspect = .75f;
                var pair = new RenderTexture[2];
                for (int side = 0; side < 2; side++)
                {
                    // Both views face the actual replay pose, with opposing three-quarter angles.
                    camera.transform.position = target + new Vector3(-3.5f, .04f, side == 0 ? 1.5f : -1.5f);
                    camera.transform.LookAt(target);
                    // Fit the exact posed upper-body silhouette, including the complete hat.
                    float minX = float.PositiveInfinity, maxX = float.NegativeInfinity;
                    float maxY = float.NegativeInfinity;
                    foreach (var point in silhouette)
                    {
                        float x = Vector3.Dot(point - target, camera.transform.right);
                        minX = Mathf.Min(minX, x); maxX = Mathf.Max(maxX, x);
                        maxY = Mathf.Max(maxY, Vector3.Dot(point - target, camera.transform.up));
                    }
                    float horizontalShift = (minX + maxX) * .5f;
                    float halfWidth = (maxX - minX) * .5f;
                    float bottomY = Vector3.Dot(new Vector3(target.x, bottom, target.z) - target, camera.transform.up);
                    float verticalShift = (maxY + bottomY) * .5f;
                    camera.transform.position += camera.transform.right * horizontalShift;
                    camera.transform.position += camera.transform.up * verticalShift;
                    float padding = height * .022f;
                    camera.orthographicSize = Mathf.Max((maxY - bottomY) * .5f + padding, (halfWidth + padding) / camera.aspect);
                    Debug.Log(FormattableString.Invariant($"DOLLFIGHT_SELECTION_FRAME id={id} side={side} upperHeight={maxY - bottomY:F3} upperWidth={halfWidth * 2:F3} frameHeight={camera.orthographicSize * 2:F3} upperFill={(maxY - bottomY) / (camera.orthographicSize * 2):F3} vertices={silhouette.Count}"));
                    lights[0].transform.rotation = camera.transform.rotation * Quaternion.Euler(22, -28, 0);
                    lights[1].transform.rotation = camera.transform.rotation * Quaternion.Euler(8, 48, 0);
                    lights[2].transform.rotation = camera.transform.rotation * Quaternion.Euler(15, 155, 0);
                    pair[side] = new RenderTexture(720, 960, 24, RenderTextureFormat.ARGB32) {
                        name = id + " selection portrait " + side, antiAliasing = 4,
                        filterMode = FilterMode.Bilinear, wrapMode = TextureWrapMode.Clamp
                    };
                    pair[side].Create(); camera.targetTexture = pair[side]; camera.Render(); camera.targetTexture = null;
                }
                images[id] = pair;
                // The small roster has its own face/shoulder composition. A wide hat must not
                // shrink the identifiable face just because the large poster fits its silhouette.
                camera.aspect = 1;
                camera.orthographicSize = height * .31f;
                Vector3 faceTarget = head - Vector3.up * height * .13f;
                camera.transform.position = faceTarget + new Vector3(-3.5f, .04f, 1.5f);
                camera.transform.LookAt(faceTarget);
                lights[0].transform.rotation = camera.transform.rotation * Quaternion.Euler(22, -28, 0);
                lights[1].transform.rotation = camera.transform.rotation * Quaternion.Euler(8, 48, 0);
                lights[2].transform.rotation = camera.transform.rotation * Quaternion.Euler(15, 155, 0);
                var roster = new RenderTexture(400, 400, 24, RenderTextureFormat.ARGB32) {
                    name = id + " roster face", antiAliasing = 4, filterMode = FilterMode.Bilinear, wrapMode = TextureWrapMode.Clamp
                };
                roster.Create(); camera.targetTexture = roster; camera.Render(); camera.targetTexture = null;
                rosterImages[id] = roster;
            }
            finally
            {
                camera.targetTexture = null; RenderTexture.active = oldActive;
                RenderSettings.ambientMode = oldMode; RenderSettings.ambientLight = oldAmbient;
                Destroy(go);
            }
        }

        static List<Vector3> UpperBodyVertices(Transform modelRoot, float bottom)
        {
            var points = new List<Vector3>();
            foreach (var renderer in modelRoot.GetComponentsInChildren<SkinnedMeshRenderer>())
            {
                if (!renderer.enabled || !renderer.gameObject.activeInHierarchy || renderer.sharedMesh == null) continue;
                var mesh = renderer.sharedMesh;
                var vertices = mesh.vertices; var weights = mesh.boneWeights;
                var binds = mesh.bindposes; var bones = renderer.bones;
                var palette = new Matrix4x4[bones.Length];
                for (int i = 0; i < bones.Length && i < binds.Length; i++)
                    if (bones[i] != null) palette[i] = bones[i].localToWorldMatrix * binds[i];
                for (int i = 0; i < vertices.Length && i < weights.Length; i++)
                {
                    var weight = weights[i]; var vertex = vertices[i];
                    Vector3 point = WeightedPoint(palette, weight.boneIndex0, weight.weight0, vertex) +
                        WeightedPoint(palette, weight.boneIndex1, weight.weight1, vertex) +
                        WeightedPoint(palette, weight.boneIndex2, weight.weight2, vertex) +
                        WeightedPoint(palette, weight.boneIndex3, weight.weight3, vertex);
                    if (point.y >= bottom) points.Add(point);
                }
            }
            foreach (var renderer in modelRoot.GetComponentsInChildren<MeshRenderer>())
            {
                if (!renderer.enabled || !renderer.gameObject.activeInHierarchy) continue;
                var filter = renderer.GetComponent<MeshFilter>();
                if (filter == null || filter.sharedMesh == null) continue;
                foreach (var vertex in filter.sharedMesh.vertices)
                {
                    var point = renderer.transform.TransformPoint(vertex);
                    if (point.y >= bottom) points.Add(point);
                }
            }
            return points;
        }

        static Vector3 WeightedPoint(Matrix4x4[] palette, int index, float weight, Vector3 vertex) =>
            weight > 0 && index >= 0 && index < palette.Length ? palette[index].MultiplyPoint3x4(vertex) * weight : Vector3.zero;

        static Light AddLight(Transform parent, string name, Color color, float intensity, Vector3 rotation)
        {
            var light = new GameObject(name).AddComponent<Light>(); light.transform.SetParent(parent, false);
            light.type = LightType.Directional; light.color = color; light.intensity = intensity;
            light.shadows = LightShadows.None; light.cullingMask = 1 << PortraitLayer;
            light.transform.rotation = Quaternion.Euler(rotation); return light;
        }

        void OnDestroy()
        {
            disposed = true; StopAllCoroutines();
            if (loadingActor != null) Destroy(loadingActor);
            foreach (var pair in images.Values) foreach (var texture in pair)
                if (texture != null) { texture.Release(); Destroy(texture); }
            foreach (var texture in rosterImages.Values) if (texture != null) { texture.Release(); Destroy(texture); }
            foreach (var material in materials) if (material != null) Destroy(material);
            images.Clear(); rosterImages.Clear(); materials.Clear();
        }
    }
}
