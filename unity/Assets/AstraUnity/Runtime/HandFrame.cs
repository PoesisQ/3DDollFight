using System;
using UnityEngine;

namespace AstraUnity
{
    /// <summary>
    /// One hand from a ``dollfight-hands-*`` datagram.
    ///
    /// Version 3 carries the hand skeleton plus the hand's own axes. The 21
    /// joints live *inside* the hand frame, so they cannot say how the palm is
    /// rolled around the forearm; ``basis`` supplies that missing turn and
    /// keeps a raised palm from rendering edge-on. Unity rebuilds the joints on
    /// the avatar's hand bone, which sits at the end of the tracked forearm.
    /// ``curls`` is kept so version 1 senders still drive the fingers.
    /// </summary>
    [Serializable]
    public sealed class HandEntry
    {
        public const int JointCount = 21;
        public const int CoordinateCount = JointCount * 3;
        public const int CurlCount = 15;
        public const int AxisCount = 9;

        public string side;
        public float confidence;
        public string gesture;
        public float scaleMm;
        public float[] joints;
        public float[] curls;
        public float[] basis;

        public bool IsLeft { get { return side == "Left"; } }

        public bool HasSkeleton { get { return joints != null && joints.Length == CoordinateCount; } }

        public bool HasBasis { get { return basis != null && basis.Length == AxisCount; } }

        /// <summary>Wrist -> middle knuckle, the axis the fingers extend along.</summary>
        public Vector3 BaseY { get { return HasBasis ? new Vector3(basis[3], basis[4], basis[5]) : Vector3.up; } }

        /// <summary>Across the palm, index knuckle towards the little finger.</summary>
        public Vector3 BaseX { get { return HasBasis ? new Vector3(basis[0], basis[1], basis[2]) : Vector3.right; } }

        /// <summary>
        /// x cross y, the axis the wrist is aimed by: the palm normal on a right
        /// hand, the back of the hand on a left hand. That asymmetry is not a
        /// bug and must not be "fixed" per side - the avatar's frame is built the
        /// same way from its own little/index knuckles, so the two agree. What
        /// has to be right is its sign in depth, which is why the sender derives
        /// that from the 2D landmarks rather than from continuity.
        /// </summary>
        public Vector3 BaseZ { get { return HasBasis ? new Vector3(basis[6], basis[7], basis[8]) : Vector3.forward; } }

        public bool IsValid(int version)
        {
            if (side != "Left" && side != "Right") return false;
            if (!Finite(confidence) || confidence < 0f || confidence > 1f) return false;
            if (version >= 2)
            {
                if (!HasSkeleton) return false;
                // ScaleMm is diagnostic only: it comes from MediaPipe's world
                // landmarks, which shrink to a third of their true value once
                // the palm turns away from the camera. The joints above are
                // rebuilt from the 2D landmarks, so this only has to catch
                // nonsense rather than measure the hand.
                if (!Finite(scaleMm) || scaleMm < 12f || scaleMm > 250f) return false;
                foreach (float value in joints)
                    if (!Finite(value) || value < -2.5f || value > 2.5f) return false;
            }
            if (version >= 3)
            {
                if (!HasBasis) return false;
                foreach (float value in basis)
                    if (!Finite(value) || value < -1.0001f || value > 1.0001f) return false;
            }
            if (curls == null) return version >= 2;
            if (curls.Length != CurlCount) return false;
            foreach (float value in curls)
                if (!Finite(value) || value < -0.0001f || value > 1.0001f) return false;
            return true;
        }

        private static bool Finite(float value) { return !float.IsNaN(value) && !float.IsInfinity(value); }
    }

    /// <summary>
    /// Hand payload kept deliberately separate from the 19 joint body frame, as
    /// required by docs/contracts.md: fingers extend through a new versioned
    /// message instead of being folded into the body dictionary.
    /// </summary>
    [Serializable]
    public sealed class HandFrame
    {
        public int version;
        public string session;
        public long sequence;
        public long timestampMs;
        public HandEntry[] hands;

        public bool IsValid()
        {
            if (version < 1 || version > 3) return false;
            if (string.IsNullOrEmpty(session) || session.Length > 128) return false;
            if (sequence < 0 || timestampMs < 0) return false;
            if (hands == null || hands.Length > 2) return false;
            bool left = false, right = false;
            foreach (var hand in hands)
            {
                if (hand == null || !hand.IsValid(version)) return false;
                if (hand.IsLeft) { if (left) return false; left = true; }
                else { if (right) return false; right = true; }
            }
            return true;
        }
    }
}
