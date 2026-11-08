using System.Collections.Generic;
using UnityEngine;

namespace AstraUnity
{
    public sealed class AstraSkeletonView : MonoBehaviour
    {
        public AstraSkeletonReceiver receiver;
        [Range(1, 2)] public int minimumJointStatus = 1;
        [Min(0.005f)] public float jointRadius = 0.035f;
        [Min(0.002f)] public float boneWidth = 0.018f;
        public bool showStatus = true;
        public float statusTop = 12;
        [Tooltip("Optional material for a custom render pipeline. Unlit materials work well.")]
        public Material jointMaterial;
        public Material boneMaterial;

        public static readonly int[,] Bones = {
            {0,18},{18,1},{1,8},{8,9},
            {1,2},{2,3},{3,16},{16,4},
            {1,5},{5,6},{6,17},{17,7},
            {9,10},{10,11},{11,12},{9,13},{13,14},{14,15}
        };

        private sealed class BodyView
        {
            public GameObject root;
            public Transform[] joints = new Transform[19];
            public LineRenderer[] bones = new LineRenderer[Bones.GetLength(0)];
        }
        private readonly Dictionary<int, BodyView> views = new Dictionary<int, BodyView>();
        private Material defaultJointMaterial, defaultBoneMaterial;
        public int VisibleBodies { get; private set; }

        private void Awake()
        {
            if (receiver == null) receiver = GetComponent<AstraSkeletonReceiver>();
            if (receiver == null) { Debug.LogError("Assign an AstraSkeletonReceiver.", this); enabled = false; return; }
            if (jointMaterial == null || boneMaterial == null)
            {
                var shader = Shader.Find("Universal Render Pipeline/Unlit") ?? Shader.Find("Unlit/Color") ?? Shader.Find("Sprites/Default");
                if (shader == null) { Debug.LogError("Assign joint and bone materials for this render pipeline.", this); enabled = false; return; }
                if (jointMaterial == null) { defaultJointMaterial = new Material(shader); defaultJointMaterial.color = new Color(0.1f,0.85f,0.9f); }
                if (boneMaterial == null) { defaultBoneMaterial = new Material(shader); defaultBoneMaterial.color = new Color(0.95f,0.7f,0.2f); }
            }
        }

        private BodyView Create(int id)
        {
            var view = new BodyView { root = new GameObject("Body " + id) };
            view.root.transform.SetParent(transform, false);
            for (int i = 0; i < 19; ++i)
            {
                var point = GameObject.CreatePrimitive(PrimitiveType.Sphere);
                point.name = ((JointType)i).ToString(); point.transform.SetParent(view.root.transform, false);
                point.GetComponent<Renderer>().sharedMaterial = jointMaterial != null ? jointMaterial : defaultJointMaterial;
                var collider = point.GetComponent<Collider>(); if (collider != null) Destroy(collider);
                view.joints[i] = point.transform;
            }
            for (int i = 0; i < view.bones.Length; ++i)
            {
                var line = new GameObject("Bone " + i).AddComponent<LineRenderer>();
                line.transform.SetParent(view.root.transform, false); line.useWorldSpace = true; line.positionCount = 2;
                line.sharedMaterial = boneMaterial != null ? boneMaterial : defaultBoneMaterial;
                view.bones[i] = line;
            }
            views.Add(id, view); return view;
        }

        private void LateUpdate()
        {
            VisibleBodies = 0;
            foreach (var item in views) item.Value.root.SetActive(false);
            if (receiver == null || !receiver.IsReceiving) return;
            var liveIds = new HashSet<int>();
            foreach (var body in receiver.LatestFrame.bodies)
            {
                if (!body.IsTracked) continue;
                liveIds.Add(body.id);
                BodyView view; if (!views.TryGetValue(body.id, out view)) view = Create(body.id);
                view.root.SetActive(true); ++VisibleBodies;
                var visible = new bool[19];
                foreach (var joint in body.joints)
                {
                    int id = joint.type;
                    visible[id] = joint.status >= minimumJointStatus;
                    view.joints[id].gameObject.SetActive(visible[id]);
                    if (!visible[id]) continue;
                    view.joints[id].position = receiver.ToWorldPosition(joint.position);
                    view.joints[id].localScale = Vector3.one * jointRadius * 2;
                }
                for (int i = 0; i < view.bones.Length; ++i)
                {
                    int a = Bones[i,0], b = Bones[i,1]; var line = view.bones[i];
                    line.enabled = visible[a] && visible[b]; line.startWidth = line.endWidth = boneWidth;
                    if (line.enabled) { line.SetPosition(0, view.joints[a].position); line.SetPosition(1, view.joints[b].position); }
                }
            }
            // Reclaim departed body IDs so repeated sessions cannot accumulate scene objects.
            var remove = new List<int>();
            foreach (var item in views) if (!liveIds.Contains(item.Key)) remove.Add(item.Key);
            foreach (int id in remove) { Destroy(views[id].root); views.Remove(id); }
        }

        private void OnGUI()
        {
            if (!showStatus || receiver == null) return;
            string state = !string.IsNullOrEmpty(receiver.LastError) ? receiver.LastError :
                !receiver.IsReceiving ? "Waiting for skeleton data on UDP " + receiver.port :
                (receiver.LatestFrame.simulated ? "SIMULATED DATA" : "LIVE ASTRA") +
                " | Bodies: " + VisibleBodies + " | Frame: " + receiver.LatestFrame.sequence;
            GUI.Box(new Rect(12, statusTop, Mathf.Min(Screen.width - 24, 780), 42), state);
        }

        private void OnDisable() { foreach (var item in views) if (item.Value.root != null) item.Value.root.SetActive(false); }
        private void OnDestroy()
        {
            foreach (var item in views) if (item.Value.root != null) Destroy(item.Value.root);
            views.Clear();
            if (defaultJointMaterial != null) Destroy(defaultJointMaterial);
            if (defaultBoneMaterial != null) Destroy(defaultBoneMaterial);
        }
    }
}
