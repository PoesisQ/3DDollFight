using System;
using System.IO;
using System.Threading;
using System.Threading.Tasks;
using UniVRM10;
using UnityEngine;

namespace DollFight
{
    [Serializable] public class MotionFrame
    {
        public float time;
        public Vector3 root;
        public Quaternion[] rotations;
        public float handClose = 0.15f;
    }

    [Serializable] public class MotionClip
    {
        public string version, coordinates, rotationSpace;
        public float fps;
        public Vector3[] rest;
        public MotionFrame[] frames;
    }

    // Apply global DELTA rotations to each model's captured T-pose bind basis.
    // Copying canonical local quaternions directly into a Humanoid hierarchy
    // would fail on extra upperChest/shoulder nodes and different bind axes.
    [DefaultExecutionOrder(10000)]
    public sealed class HumanoidReplay : MonoBehaviour
    {
        public string vrmPath;
        public TextAsset replayJson;
        public Animator existingHumanoid;
        public bool playing = true;
        [Range(0.1f, 2)] public float speed = 1;
        public float time;
        public string status = "Choose a VRM and exported replay JSON";
        public bool externallyDriven;
        public bool Ready => ready;
        public Vrm10Instance Instance => instance;
        public Transform ModelRoot => modelRoot;
        public Transform[] Bones => bones;
        public float Duration => clip?.frames[clip.frames.Length - 1].time ?? 0;

        public static readonly HumanBodyBones[] BoneOrder = {
            HumanBodyBones.Hips, HumanBodyBones.Spine, HumanBodyBones.Chest,
            HumanBodyBones.Neck, HumanBodyBones.Head,
            HumanBodyBones.LeftUpperArm, HumanBodyBones.LeftLowerArm, HumanBodyBones.LeftHand,
            HumanBodyBones.RightUpperArm, HumanBodyBones.RightLowerArm, HumanBodyBones.RightHand,
            HumanBodyBones.LeftUpperLeg, HumanBodyBones.LeftLowerLeg, HumanBodyBones.LeftFoot, HumanBodyBones.LeftToes,
            HumanBodyBones.RightUpperLeg, HumanBodyBones.RightLowerLeg, HumanBodyBones.RightFoot, HumanBodyBones.RightToes
        };
        MotionClip clip;
        Transform modelRoot;
        Transform[] bones;
        Quaternion[] bindWorld;
        Vrm10Instance instance;
        CancellationTokenSource cancellation;
        float rootScale;
        float bindHipHeight;
        AvatarSoleContact soles;
        readonly Vector3[] sourcePoints = new Vector3[19];
        readonly Quaternion[] sourceRotations = new Quaternion[19];
        static readonly int[] Parents = { -1, 0, 1, 2, 3, 2, 5, 6, 2, 8, 9, 0, 11, 12, 13, 0, 15, 16, 17 };
        float previousTime = -1;
        bool ready;
        Transform[] fingerBones;
        Quaternion[] fingerBinds;
        Vector3[] fingerAxes;
        float[] fingerAngles;
        Transform[] restNodes;
        Vector3[] restPositions;
        Quaternion[] restRotations;

        async void Start()
        {
            if (externallyDriven) return;
            await LoadAsync(vrmPath, replayJson != null ? replayJson.text : null);
        }

        public async Task LoadAsync(string modelPath, string json)
        {
            cancellation = new CancellationTokenSource();
            try
            {
                if (string.IsNullOrWhiteSpace(json)) throw new InvalidOperationException("Assign an exported Unity replay JSON");
                clip = JsonUtility.FromJson<MotionClip>(json);
                ValidateClip(clip);
                Animator animator = existingHumanoid;
                if (animator == null)
                {
                    if (!File.Exists(modelPath)) throw new FileNotFoundException("Choose a local .vrm file", modelPath);
                    instance = await Vrm10.LoadPathAsync(modelPath,
                        controlRigGenerationOption: ControlRigGenerationOption.None,
                        showMeshes: true, ct: cancellation.Token);
                    if (cancellation.IsCancellationRequested) { if (instance != null) Destroy(instance.gameObject); return; }
                    if (instance == null) throw new InvalidOperationException("UniVRM returned no model");
                    instance.transform.SetParent(transform, false);
                    // Own body pose, then explicitly process VRM constraints,
                    // expressions and native job-based hair springs once.
                    instance.UpdateType = Vrm10Instance.UpdateTypes.None;
                    animator = instance.GetComponent<Animator>();
                }
                Bind(animator);
                BindFingers(animator);
                restNodes = modelRoot.GetComponentsInChildren<Transform>();
                restPositions = Array.ConvertAll(restNodes, t => t.localPosition);
                restRotations = Array.ConvertAll(restNodes, t => t.localRotation);
                ready = true;
                status = "19/19 Humanoid bones bound; deterministic replay";
                Apply(0);
            }
            catch (OperationCanceledException) { }
            catch (Exception error)
            {
                status = error.Message; Debug.LogException(error, this);
                if (externallyDriven) throw;
            }
        }

        public static void ValidateClip(MotionClip value)
        {
            if (value == null || value.version != "dollfight-humanoid-1" ||
                value.coordinates != "stage_rh_y_up_meters" ||
                value.rotationSpace != "global_delta_from_canonical_t_pose" ||
                value.rest == null || value.rest.Length != 19 || value.frames == null || value.frames.Length < 2)
                throw new ArgumentException("Unsupported replay format / coordinate space");
            float previous = -1;
            foreach (MotionFrame frame in value.frames)
            {
                if (frame == null || frame.time <= previous || float.IsNaN(frame.time) ||
                    float.IsInfinity(frame.time) || frame.rotations == null || frame.rotations.Length != 19)
                    throw new ArgumentException("Invalid frame timestamps or rotation count");
                foreach (Quaternion q in frame.rotations)
                    if (float.IsNaN(q.x + q.y + q.z + q.w) || float.IsInfinity(q.x + q.y + q.z + q.w) ||
                        Mathf.Abs(q.x*q.x + q.y*q.y + q.z*q.z + q.w*q.w - 1) > 0.01f)
                        throw new ArgumentException("Invalid unit quaternion");
                if (float.IsNaN(frame.root.sqrMagnitude) || float.IsInfinity(frame.root.sqrMagnitude))
                    throw new ArgumentException("Invalid root position");
                previous = frame.time;
            }
            if (!(value.rest[0].y > 0.2f && value.rest[0].y < 2.5f))
                throw new ArgumentException("Invalid meter-scale rest pose");
        }

        void Bind(Animator animator)
        {
            if (animator == null || animator.avatar == null || !animator.avatar.isValid || !animator.avatar.isHuman)
                throw new ArgumentException("Avatar must be a valid Unity Humanoid in its imported T-pose");
            animator.enabled = false;
            modelRoot = animator.transform;
            bones = new Transform[19];
            bindWorld = new Quaternion[19];
            for (int i = 0; i < 19; i++)
            {
                bones[i] = animator.GetBoneTransform(BoneOrder[i]);
                if (bones[i] == null) throw new ArgumentException("Missing mapped bone: " + BoneOrder[i]);
                bindWorld[i] = Quaternion.Inverse(modelRoot.rotation) * bones[i].rotation;
            }
            bindHipHeight = transform.InverseTransformPoint(bones[0].position).y;
            float targetLeg = (Vector3.Distance(bones[11].position, bones[12].position) +
                Vector3.Distance(bones[12].position, bones[13].position) +
                Vector3.Distance(bones[15].position, bones[16].position) +
                Vector3.Distance(bones[16].position, bones[17].position)) * 0.5f;
            float sourceLeg = (Vector3.Distance(clip.rest[11], clip.rest[12]) +
                Vector3.Distance(clip.rest[12], clip.rest[13]) +
                Vector3.Distance(clip.rest[15], clip.rest[16]) +
                Vector3.Distance(clip.rest[16], clip.rest[17])) * 0.5f;
            rootScale = targetLeg / sourceLeg;
            if (!(rootScale > 0.1f && rootScale < 5f)) throw new ArgumentException("Check avatar height and model root scale");
            if (existingHumanoid != null)
            {
                soles = new AvatarSoleContact(modelRoot, bones);
                bindHipHeight += soles.RestFloorOffset;
            }
        }

        // UniVRM 1.0 imports glTF with X reflection, not generic glTF Z
        // reflection. Motion and bind skeleton MUST use the same convention.
        public static Quaternion StageToUnity(Quaternion q) => new Quaternion(q.x, -q.y, -q.z, q.w);
        public static Vector3 StageToUnity(Vector3 p) => new Vector3(-p.x, p.y, p.z);

        public static Vector3 MapRoot(Vector3 root, float sourceHip, float targetHip, float legRatio)
        {
            Vector3 position = StageToUnity(root);
            // Arena travel is in metres, independent of an FBX's import scale.
            // Only vertical crouch/jump displacement follows leg proportions.
            position.y = targetHip + (root.y - sourceHip) * legRatio;
            return position;
        }

        void LateUpdate()
        {
            if (!ready || externallyDriven) return;
            float duration = clip.frames[clip.frames.Length - 1].time;
            if (playing) time = Mathf.Repeat(time + Time.deltaTime * speed, duration);
            Apply(time);
            ProcessSecondary();
        }

        public void Apply(float seconds)
        {
            if (!ready) return;
            int low = 0, high = clip.frames.Length - 1;
            while (low < high) { int m = (low + high + 1) / 2; if (clip.frames[m].time <= seconds) low = m; else high = m - 1; }
            MotionFrame a = clip.frames[low], b = clip.frames[Math.Min(low + 1, clip.frames.Length - 1)];
            float alpha = b.time > a.time ? Mathf.Clamp01((seconds - a.time) / (b.time - a.time)) : 0;
            bones[0].position = transform.TransformPoint(MapRoot(Vector3.Lerp(a.root, b.root, alpha), clip.rest[0].y, bindHipHeight, rootScale));
            sourcePoints[0] = Vector3.Lerp(a.root, b.root, alpha);
            for (int i = 0; i < 19; i++)
            {
                sourceRotations[i] = Quaternion.Slerp(a.rotations[i], b.rotations[i], alpha);
                bones[i].rotation = modelRoot.rotation * StageToUnity(sourceRotations[i]) * bindWorld[i];
                if (i > 0) sourcePoints[i] = sourcePoints[Parents[i]] + sourceRotations[Parents[i]] * (clip.rest[i] - clip.rest[Parents[i]]);
            }
            float delta = seconds - previousTime;
            soles?.Apply(sourcePoints, clip.rest, rootScale, Mathf.Clamp(delta, 1f / 120, 0.1f), previousTime < 0 || delta < 0 || delta > 0.2f);
            previousTime = seconds;
            float close = Mathf.Clamp01(Mathf.Lerp(a.handClose, b.handClose, alpha));
            for (int i = 0; i < fingerBones.Length; i++)
                fingerBones[i].localRotation = fingerBinds[i] *
                    Quaternion.AngleAxis((0.08f + close) * fingerAngles[i], fingerAxes[i]);
        }

        public void ProcessSecondary() { if (ready && instance != null) instance.Runtime.Process(); }

        public void RestoreBindPose()
        {
            for (int i = 0; i < restNodes.Length; i++)
            {
                restNodes[i].localPosition = restPositions[i];
                restNodes[i].localRotation = restRotations[i];
            }
        }

        public void ResetSecondary()
        {
            if (ready && instance != null) instance.Runtime.SpringBone.RestoreInitialTransform();
        }

        void BindFingers(Animator animator)
        {
            var nodes = new System.Collections.Generic.List<Transform>();
            var binds = new System.Collections.Generic.List<Quaternion>();
            var axes = new System.Collections.Generic.List<Vector3>();
            var angles = new System.Collections.Generic.List<float>();
            foreach (string side in new[] { "Left", "Right" })
                foreach (string finger in new[] { "Index", "Middle", "Ring", "Little", "Thumb" })
                    for (int segment = 0; segment < 3; segment++)
                    {
                        string suffix = new[] { "Proximal", "Intermediate", "Distal" }[segment];
                        if (!Enum.TryParse(side + finger + suffix, out HumanBodyBones id)) continue;
                        Transform node = animator.GetBoneTransform(id);
                        if (node == null) continue;
                        Vector3 axis = finger == "Thumb" ? Vector3.up : Vector3.forward;
                        axis *= side == "Left" ? -1 : 1;
                        axis = new Vector3(axis.x, -axis.y, -axis.z);
                        // Display prior, not inferred finger tracking. Map its
                        // canonical axis into the imported raw bone basis.
                        axes.Add(node.InverseTransformDirection(modelRoot.TransformDirection(axis)));
                        angles.Add(finger == "Thumb" ? 32 : new[] { 82f, 98f, 58f }[segment]);
                        nodes.Add(node); binds.Add(node.localRotation);
                    }
            fingerBones = nodes.ToArray(); fingerBinds = binds.ToArray();
            fingerAxes = axes.ToArray(); fingerAngles = angles.ToArray();
        }

        void OnDestroy()
        {
            ready = false;
            cancellation?.Cancel();
            cancellation?.Dispose();
            if (instance != null) Destroy(instance.gameObject);
        }
    }
}
