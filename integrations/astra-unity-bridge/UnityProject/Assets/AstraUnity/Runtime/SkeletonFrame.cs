using System;
using UnityEngine;

namespace AstraUnity
{
    public enum JointType
    {
        Head, ShoulderSpine, LeftShoulder, LeftElbow, LeftHand,
        RightShoulder, RightElbow, RightHand, MidSpine, BaseSpine,
        LeftHip, LeftKnee, LeftFoot, RightHip, RightKnee, RightFoot,
        LeftWrist, RightWrist, Neck
    }

    [Serializable]
    public sealed class SkeletonJoint
    {
        public int type;
        public int status;
        public Vector3 position;
        // Astra's original 3x3 matrix, row-major. No Unity rotation conversion applied.
        public float[] orientation;
    }

    [Serializable]
    public sealed class SkeletonBody
    {
        public int id;
        public int status;
        public SkeletonJoint[] joints;
        public bool IsTracked { get { return status == 2 || status == 3; } }

        public SkeletonJoint Joint(JointType type)
        {
            if (joints == null) return null;
            foreach (var joint in joints)
                if (joint != null && joint.type == (int)type) return joint;
            return null;
        }
    }

    [Serializable]
    public sealed class SkeletonFrame
    {
        public int version;
        public string session;
        public long sequence;
        public int sourceFrame;
        public long timestampMs;
        public bool simulated;
        public string units;
        public SkeletonBody[] bodies;

        public bool IsValid()
        {
            if (version != 1 || units != "mm" || string.IsNullOrEmpty(session) ||
                session.Length > 128 || sequence < 0 || timestampMs < 0 ||
                bodies == null || bodies.Length > 6) return false;
            var bodyIds = new bool[256];
            foreach (var body in bodies)
            {
                if (body == null || body.id < 1 || body.id > 255 || bodyIds[body.id] ||
                    body.status < 0 || body.status > 3 || body.joints == null || body.joints.Length != 19)
                    return false;
                bodyIds[body.id] = true;
                int seen = 0;
                foreach (var joint in body.joints)
                {
                    if (joint == null || joint.type < 0 || joint.type >= 19 ||
                        (seen & (1 << joint.type)) != 0 || joint.status < 0 || joint.status > 2 ||
                        !Finite(joint.position.x) || !Finite(joint.position.y) || !Finite(joint.position.z) ||
                        joint.orientation == null || joint.orientation.Length != 9) return false;
                    foreach (float v in joint.orientation) if (!Finite(v)) return false;
                    seen |= 1 << joint.type;
                }
            }
            return true;
        }

        private static bool Finite(float value) { return !float.IsNaN(value) && !float.IsInfinity(value); }
    }
}
