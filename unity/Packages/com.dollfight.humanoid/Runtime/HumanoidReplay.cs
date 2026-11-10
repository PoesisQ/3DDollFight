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
        [Tooltip("World-rotation smoothing for tracked finger bones, in 1/s.")]
        public float handSmoothing = 18f;
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
        int[] fingerSlots;
        // Hand skeleton: 21 landmarks rebuilt on the wrist bone, which is the
        // end of the arm the body tracker already poses.
        const int HandPointCount = 21;
        static readonly int[][] HandChains = {
            new[] { 0, 1, 2, 3, 4 }, new[] { 0, 5, 6, 7, 8 }, new[] { 0, 9, 10, 11, 12 },
            new[] { 0, 13, 14, 15, 16 }, new[] { 0, 17, 18, 19, 20 }
        };
        static readonly string[] HandFingers = { "Thumb", "Index", "Middle", "Ring", "Little" };
        readonly Transform[] handRoots = new Transform[2];
        readonly Vector3[] handLocalX = new Vector3[2];
        readonly Vector3[] handLocalY = new Vector3[2];
        readonly Vector3[] handLocalZ = new Vector3[2];
        readonly float[] handLengths = new float[2];
        readonly Quaternion[] handLocalBinds = new Quaternion[2];
        readonly float[] handRolls = new float[2];
        Transform[][] handBones;
        Vector3[][] handBindDirections;
        Quaternion[][] handBindRotations;
        int[][] handTargets;
        int[][] handParents;
        bool handsBound;
        // The avatars in this project leave the finger slots of their Humanoid
        // avatar empty, so Animator.GetBoneTransform returns null for every
        // finger even though the bones exist. Keep a name index to fall back on.
        System.Collections.Generic.Dictionary<string, Transform> bonesByName;
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
                        showMeshes: true, ct: cancellation.Token,
                        // Own the job buffers with this avatar. The shared service
                        // defers removal across scene reloads after disposing them.
                        springboneRuntime: new Vrm10FastSpringboneRuntimeStandalone());
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
                BindHandSkeletons(animator);
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
            CacheBoneNames();
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
            var slots = new System.Collections.Generic.List<int>();
            // Curl slots follow the dollfight-hands-1 order: Thumb, Index, Middle,
            // Ring, Little, and Left before Right.
            string[] fingers = { "Thumb", "Index", "Middle", "Ring", "Little" };
            for (int sideIndex = 0; sideIndex < 2; sideIndex++)
            {
                string side = sideIndex == 0 ? "Left" : "Right";
                for (int fingerIndex = 0; fingerIndex < fingers.Length; fingerIndex++)
                {
                    string finger = fingers[fingerIndex];
                    for (int segment = 0; segment < 3; segment++)
                    {
                        string suffix = new[] { "Proximal", "Intermediate", "Distal" }[segment];
                        Transform node = FingerBone(animator, side, finger, suffix);
                        if (node == null) continue;
                        Vector3 axis = finger == "Thumb" ? Vector3.up : Vector3.forward;
                        axis *= side == "Left" ? -1 : 1;
                        axis = new Vector3(axis.x, -axis.y, -axis.z);
                        // Display prior, not inferred finger tracking. Map its
                        // canonical axis into the imported raw bone basis.
                        axes.Add(node.InverseTransformDirection(modelRoot.TransformDirection(axis)));
                        angles.Add(finger == "Thumb" ? 32 : new[] { 82f, 98f, 58f }[segment]);
                        nodes.Add(node); binds.Add(node.localRotation);
                        slots.Add(sideIndex * 15 + fingerIndex * 3 + segment);
                    }
                }
            }
            fingerBones = nodes.ToArray(); fingerBinds = binds.ToArray();
            fingerAxes = axes.ToArray(); fingerAngles = angles.ToArray();
            fingerSlots = slots.ToArray();
        }

        public bool FingersReady { get { return ready && fingerBones != null && fingerBones.Length > 0; } }

        /// <summary>
        /// Applies tracked finger curls indexed as
        /// ``side * 15 + finger * 3 + segment`` (left = 0, right = 1).
        /// A negative value keeps that joint at its bind pose, which lets one
        /// hand stay tracked while the other is out of view.
        /// </summary>
        public void ApplyFingerCurls(float[] curls)
        {
            if (!FingersReady || curls == null || curls.Length < 30) return;
            for (int i = 0; i < fingerBones.Length; i++)
            {
                int slot = fingerSlots[i];
                if (slot < 0 || slot >= curls.Length) continue;
                float curl = curls[slot];
                if (curl < 0f) continue;
                float angle = Mathf.Lerp(0.06f, 1f, Mathf.Clamp01(curl)) * fingerAngles[i];
                fingerBones[i].localRotation = fingerBinds[i] * Quaternion.AngleAxis(angle, fingerAxes[i]);
            }
        }

        void CacheBoneNames()
        {
            bonesByName = new System.Collections.Generic.Dictionary<string, Transform>();
            foreach (Transform node in modelRoot.GetComponentsInChildren<Transform>(true))
            {
                string key = NormaliseBoneName(node.name);
                // "Left_IndexDistalEnd" is a leaf marker, not a finger joint.
                if (key.Length == 0 || key.EndsWith("end", StringComparison.Ordinal)) continue;
                if (!bonesByName.ContainsKey(key)) bonesByName[key] = node;
            }
        }

        static string NormaliseBoneName(string value)
        {
            var builder = new System.Text.StringBuilder(value.Length);
            foreach (char c in value)
                if (char.IsLetterOrDigit(c)) builder.Append(char.ToLowerInvariant(c));
            return builder.ToString();
        }

        Transform FindBone(string name)
        {
            if (bonesByName == null || string.IsNullOrEmpty(name)) return null;
            return bonesByName.TryGetValue(NormaliseBoneName(name), out Transform node) ? node : null;
        }

        Transform BodyOrNamed(Animator animator, HumanBodyBones id, string fallback)
        {
            Transform mapped = animator.GetBoneTransform(id);
            return mapped != null ? mapped : FindBone(fallback);
        }

        Transform FingerBone(Animator animator, string side, string finger, string suffix)
        {
            if (Enum.TryParse(side + finger + suffix, out HumanBodyBones id))
            {
                Transform mapped = animator.GetBoneTransform(id);
                if (mapped != null) return mapped;
            }
            Transform node = FindBone(side + finger + suffix);
            // Tripo exports the little finger as "Pinky"; Unity calls it Little.
            if (node == null && finger == "Little") node = FindBone(side + "Pinky" + suffix);
            if (node == null && finger == "Pinky") node = FindBone(side + "Little" + suffix);
            return node;
        }

        void BindHandSkeletons(Animator animator)
        {
            handBones = new Transform[2][];
            handBindDirections = new Vector3[2][];
            handBindRotations = new Quaternion[2][];
            handTargets = new int[2][];
            handParents = new int[2][];
            handsBound = false;
            bool any = false;
            for (int sideIndex = 0; sideIndex < 2; sideIndex++)
            {
                string side = sideIndex == 0 ? "Left" : "Right";
                Transform hand = BodyOrNamed(animator, sideIndex == 0
                    ? HumanBodyBones.LeftHand : HumanBodyBones.RightHand, side + "Hand");
                Transform index = FingerBone(animator, side, "Index", "Proximal");
                Transform middle = FingerBone(animator, side, "Middle", "Proximal");
                Transform little = FingerBone(animator, side, "Little", "Proximal");
                bool usable = hand != null && index != null && middle != null && little != null;
                Vector3 along = usable ? middle.position - hand.position : Vector3.zero;
                Vector3 across = usable ? little.position - index.position : Vector3.zero;
                if (along.sqrMagnitude < 1e-8f) usable = false;
                else
                {
                    across -= along.normalized * Vector3.Dot(across, along.normalized);
                    if (across.sqrMagnitude < 1e-8f) usable = false;
                }
                if (!usable)
                {
                    handBones[sideIndex] = new Transform[0];
                    handBindDirections[sideIndex] = new Vector3[0];
                    handBindRotations[sideIndex] = new Quaternion[0];
                    handTargets[sideIndex] = new int[0];
                    handParents[sideIndex] = new int[0];
                    continue;
                }
                Vector3 y = along.normalized;
                Vector3 x = across.normalized;
                Vector3 z = Vector3.Cross(x, y);
                handRoots[sideIndex] = hand;
                handLengths[sideIndex] = along.magnitude;
                handLocalBinds[sideIndex] = hand.localRotation;
                handRolls[sideIndex] = 0f;
                // Store the anatomical frame in the hand bone's own space so it
                // follows the wrist when the arm moves.
                handLocalX[sideIndex] = hand.InverseTransformDirection(x);
                handLocalY[sideIndex] = hand.InverseTransformDirection(y);
                handLocalZ[sideIndex] = hand.InverseTransformDirection(z);
                var bones = new System.Collections.Generic.List<Transform>();
                var directions = new System.Collections.Generic.List<Vector3>();
                var rotations = new System.Collections.Generic.List<Quaternion>();
                var targets = new System.Collections.Generic.List<int>();
                var parents = new System.Collections.Generic.List<int>();
                for (int finger = 0; finger < HandFingers.Length; finger++)
                {
                    var chain = HandChains[finger];
                    var segments = new System.Collections.Generic.List<Transform>();
                    for (int segment = 0; segment < 3; segment++)
                    {
                        string suffix = new[] { "Proximal", "Intermediate", "Distal" }[segment];
                        Transform node = FingerBone(animator, side, HandFingers[finger], suffix);
                        if (node != null) segments.Add(node);
                    }
                    int count = segments.Count;
                    for (int k = 0; k < count; k++)
                    {
                        Transform bone = segments[k];
                        // Three bones cover MCP->PIP, PIP->DIP, DIP->TIP. Fewer
                        // bones spread over the same chain instead of skipping
                        // the fingertip.
                        int target = count == 1 ? chain[4] : chain[2 + Mathf.RoundToInt(k * 2f / (count - 1))];
                        Vector3 direction;
                        if (k + 1 < count) direction = segments[k + 1].position - bone.position;
                        else if (k > 0) direction = bone.position - segments[k - 1].position;
                        else direction = hand.position - bone.position;
                        if (direction.sqrMagnitude < 1e-10f) continue;
                        bones.Add(bone);
                        directions.Add(bone.InverseTransformDirection(direction.normalized));
                        rotations.Add(bone.localRotation);
                        targets.Add(target);
                        parents.Add(chain[1 + k]);
                    }
                }
                handBones[sideIndex] = bones.ToArray();
                handBindDirections[sideIndex] = directions.ToArray();
                handBindRotations[sideIndex] = rotations.ToArray();
                handTargets[sideIndex] = targets.ToArray();
                handParents[sideIndex] = parents.ToArray();
                any |= bones.Count > 0;
            }
            handsBound = any;
            if (!any) Debug.LogWarning("No finger bones resolved on " + name + "; hand tracking will be ignored. Check the avatar hierarchy.", this);
        }

        public bool HandsReady { get { return ready && handsBound; } }

        /// <summary>Number of finger bones resolved for the 21-point skeleton.</summary>
        public int HandBoneCount
        {
            get
            {
                if (handBones == null) return 0;
                int total = 0;
                for (int i = 0; i < handBones.Length; i++)
                    if (handBones[i] != null) total += handBones[i].Length;
                return total;
            }
        }

        /// <summary>Number of curl-driven finger bones (the version 1 fallback).</summary>
        public int CurlBoneCount { get { return fingerBones == null ? 0 : fingerBones.Length; } }

        /// <summary>
        /// Current wrist roll in degrees, or 0 when the hand is not driven.
        /// Exposed for diagnostics: if this does not move while the palm turns,
        /// the sender's basis is not reaching this hand.
        /// </summary>
        public float HandRollDegrees(bool isLeft) { return handRolls[isLeft ? 0 : 1]; }

        /// <summary>
        /// Rebuilds 21 tracked hand joints on the wrist bone and aims every
        /// finger bone at its target. Points are in the hand's own frame,
        /// normalised by palm length, so the same data drives any avatar size.
        /// </summary>
        /// <param name="humanX">Index knuckle to little knuckle, in world space.</param>
        /// <param name="humanY">Wrist to middle knuckle, in world space.</param>
        /// <param name="humanZ">
        /// Back-of-hand normal in world space, or <c>Vector3.zero</c> when the
        /// sender has no wrist rotation. The 21 joints live inside the hand's
        /// own frame, so they cannot say how the whole hand is oriented; the
        /// three axes supply exactly that, and drive the wrist in all three
        /// degrees of freedom instead of only the roll around the forearm.
        /// </param>
        public void ApplyHandSkeleton(bool isLeft, Vector3[] points,
                                      Vector3 humanX, Vector3 humanY, Vector3 humanZ)
        {
            if (!HandsReady || points == null || points.Length < HandPointCount) return;
            int side = isLeft ? 0 : 1;
            Transform hand = handRoots[side];
            var bones = handBones[side];
            if (hand == null || bones == null || bones.Length == 0) return;
            float t = Mathf.Clamp01(1f - Mathf.Exp(-Mathf.Max(0.01f, handSmoothing) * Time.deltaTime));
            if (humanY.sqrMagnitude > 1e-6f && humanZ.sqrMagnitude > 1e-6f)
            {
                Vector3 avatarY = hand.rotation * handLocalY[side];
                Vector3 avatarZ = hand.rotation * handLocalZ[side];
                if (avatarY.sqrMagnitude > 1e-8f && avatarZ.sqrMagnitude > 1e-8f)
                {
                    // Map the avatar's own hand frame onto the tracked one:
                    // back-of-hand normal and finger direction both line up, so
                    // palm-up/palm-down and wrist pitch follow the real hand.
                    Quaternion from = Quaternion.LookRotation(avatarZ, avatarY);
                    Quaternion to = Quaternion.LookRotation(humanZ, humanY);
                    Quaternion target = to * Quaternion.Inverse(from) * hand.rotation;
                    hand.rotation = Quaternion.Slerp(hand.rotation, target, t);
                    handRolls[side] = Quaternion.Angle(hand.localRotation, handLocalBinds[side]);
                }
            }
            Vector3 x = hand.rotation * handLocalX[side];
            Vector3 y = hand.rotation * handLocalY[side];
            Vector3 z = hand.rotation * handLocalZ[side];
            // Aim *from where the bone already is*, not from the bind pose.
            //
            // This loop used to reset every bone to its bind local rotation and
            // then slerp `t` of the way to the target. Because the reset undid
            // the previous frame's progress, the bones never accumulated it: the
            // pose held at a fixed fraction `t` of the target instead of
            // converging on it. At 60 fps that is 26 %, so a fist closed to
            // 114 degrees of the 255 a real one reaches (84 at 90 fps) - a loose
            // claw, and the wrist, having the same defect, turned only 23 of 90
            // degrees. Both were reported as "the hand skeleton is a mess and I
            // cannot get a fist".
            //
            // Aiming with a relative rotation is safe from frame to frame:
            // `handBindDirections` is a direction in the bone's own space, so
            // `bone.rotation * direction` is the bone's real direction no matter
            // how the bone got there. `FromToRotation` therefore only has to
            // remove the difference that is left, and the slerp is a genuine
            // first-order filter that settles on the tracked pose in about four
            // frames (67 ms).
            for (int i = 0; i < bones.Length; i++)
            {
                Transform bone = bones[i];
                if (bone == null) continue;
                int target = handTargets[side][i];
                int from = handParents[side][i];
                if (target < 0 || target >= points.Length) continue;
                if (from < 0 || from >= points.Length) continue;
                // Aim along the *tracked* segment, not at the tracked joint.
                // Aiming at the joint mixes in the difference between the
                // avatar's bone lengths and the real hand's, which is what made
                // a closing fist look like fingers merely sliding together.
                Vector3 a = points[from];
                Vector3 b = points[target];
                Vector3 desired = x * (b.x - a.x) + y * (b.y - a.y) + z * (b.z - a.z);
                if (desired.sqrMagnitude < 1e-10f) continue;
                Vector3 current = bone.rotation * handBindDirections[side][i];
                if (Vector3.Angle(current, desired) < 0.15f) continue;
                bone.rotation = Quaternion.Slerp(bone.rotation,
                    Quaternion.FromToRotation(current, desired.normalized) * bone.rotation, t);
            }
        }

        /// <summary>Drops the wrist roll so the next frame re-derives it from scratch.</summary>
        public void ResetHandRoll()
        {
            for (int i = 0; i < handRolls.Length; i++) handRolls[i] = 0f;
        }

        /// <summary>Eases one hand back to its bind pose when tracking is lost.</summary>
        public void RelaxHand(bool isLeft)
        {
            if (!HandsReady) return;
            int side = isLeft ? 0 : 1;
            var bones = handBones[side];
            if (bones == null) return;
            float t = 1f - Mathf.Exp(-8f * Time.deltaTime);
            Transform hand = handRoots[side];
            if (hand != null)
            {
                // Ease the wrist itself back; handRolls is now a measurement, not
                // the angle being applied, so replaying it here would add a
                // rotation that was never commanded.
                hand.localRotation = Quaternion.Slerp(hand.localRotation, handLocalBinds[side], t);
                handRolls[side] = Mathf.LerpAngle(handRolls[side], 0f, t);
            }
            for (int i = 0; i < bones.Length; i++)
            {
                if (bones[i] == null) continue;
                bones[i].localRotation = Quaternion.Slerp(bones[i].localRotation, handBindRotations[side][i], t);
            }
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
