using System;
using System.IO;
using System.Threading;
using UniVRM10;
using UnityEngine;

namespace DollFight
{
    [Serializable] public class MotionFrame
    {
        public float time;
        public Vector3 root;
        public Quaternion[] rotations;
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
        bool ready;

        async void Start()
        {
            cancellation = new CancellationTokenSource();
            try
            {
                if (replayJson == null) throw new InvalidOperationException("Assign an exported Unity replay JSON");
                clip = JsonUtility.FromJson<MotionClip>(replayJson.text);
                ValidateClip(clip);
                Animator animator = existingHumanoid;
                if (animator == null)
                {
                    if (!File.Exists(vrmPath)) throw new FileNotFoundException("Choose a local .vrm file", vrmPath);
                    instance = await Vrm10.LoadPathAsync(vrmPath, showMeshes: true, ct: cancellation.Token);
                    if (cancellation.IsCancellationRequested) { if (instance != null) Destroy(instance.gameObject); return; }
                    if (instance == null) throw new InvalidOperationException("UniVRM returned no model");
                    instance.transform.SetParent(transform, false);
                    // Offline deterministic replay owns bones; do not let the
                    // generated control rig overwrite them in LateUpdate.
                    // Secondary spring/constraint simulation is deliberately off.
                    instance.enabled = false;
                    animator = instance.GetComponent<Animator>();
                }
                Bind(animator);
                ready = true;
                status = "19/19 Humanoid bones bound; deterministic replay";
                Apply(0);
            }
            catch (OperationCanceledException) { }
            catch (Exception error) { status = error.Message; Debug.LogException(error, this); }
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
            rootScale = modelRoot.InverseTransformPoint(bones[0].position).y / clip.rest[0].y;
            if (!(rootScale > 0.1f && rootScale < 5f)) throw new ArgumentException("Check avatar height and model root scale");
        }

        // H = diag(1,1,-1): R_unity = H R_stage H^-1.
        public static Quaternion StageToUnity(Quaternion q) => new Quaternion(-q.x, -q.y, q.z, q.w);
        public static Vector3 StageToUnity(Vector3 p) => new Vector3(p.x, p.y, -p.z);

        void LateUpdate()
        {
            if (!ready) return;
            float duration = clip.frames[clip.frames.Length - 1].time;
            if (playing) time = Mathf.Repeat(time + Time.deltaTime * speed, duration);
            Apply(time);
        }

        public void Apply(float seconds)
        {
            if (!ready) return;
            int low = 0, high = clip.frames.Length - 1;
            while (low < high) { int m = (low + high + 1) / 2; if (clip.frames[m].time <= seconds) low = m; else high = m - 1; }
            MotionFrame a = clip.frames[low], b = clip.frames[Math.Min(low + 1, clip.frames.Length - 1)];
            float alpha = b.time > a.time ? Mathf.Clamp01((seconds - a.time) / (b.time - a.time)) : 0;
            bones[0].position = modelRoot.TransformPoint(StageToUnity(Vector3.Lerp(a.root, b.root, alpha)) * rootScale);
            for (int i = 0; i < 19; i++)
                bones[i].rotation = modelRoot.rotation * StageToUnity(Quaternion.Slerp(a.rotations[i], b.rotations[i], alpha)) * bindWorld[i];
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
