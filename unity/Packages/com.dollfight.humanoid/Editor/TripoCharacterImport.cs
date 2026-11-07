using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEngine;

namespace DollFight.Editor
{
    public static class TripoCharacterImport
    {
        const string Folder = "Assets/Art/TripoB9E9/";
        const string ModelPath = Folder + "TripoB9E9.fbx";
        public const string PrefabPath = "Assets/Resources/DollFight/Characters/TripoB9E9.prefab";

        [MenuItem("DollFight/Prepare Tripo B9E9 Character")]
        public static void Prepare()
        {
            AssetDatabase.Refresh(ImportAssetOptions.ForceSynchronousImport);
            var importer = AssetImporter.GetAtPath(ModelPath) as ModelImporter;
            if (importer == null) throw new FileNotFoundException("Run tools/prepare_tripo_character.py first", ModelPath);
            // Read the supplied hierarchy first. Its explicit Left_UpperArm /
            // Left_PinkyProximal names must not depend on Unity's name guessing.
            importer.animationType = ModelImporterAnimationType.Generic;
            importer.avatarSetup = ModelImporterAvatarSetup.NoAvatar;
            importer.importAnimation = false;
            importer.optimizeGameObjects = false;
            importer.isReadable = true;
            importer.meshCompression = ModelImporterMeshCompression.Off;
            importer.materialImportMode = ModelImporterMaterialImportMode.None;
            importer.useFileScale = true;
            importer.globalScale = 1;
            importer.SaveAndReimport();

            var raw = UnityEngine.Object.Instantiate(AssetDatabase.LoadAssetAtPath<GameObject>(ModelPath));
            HumanDescription description;
            try
            {
                // SkeletonBone's root name must agree with the imported model.
                raw.name = AssetDatabase.LoadAssetAtPath<GameObject>(ModelPath).name;
                var nodes = raw.GetComponentsInChildren<Transform>().ToDictionary(t => t.name);
                VerifySourceCoordinates(nodes);
                // The original is a slightly lowered-arm pose. Rotate the
                // actual skinned joints, then use those same local transforms
                // both in the Avatar description and the saved replay bind.
                foreach (string side in new[] { "Left", "Right" })
                {
                    Vector3 direction = side == "Left" ? Vector3.left : Vector3.right;
                    Aim(nodes[side + "_UpperArm"], nodes[side + "_LowerArm"], direction);
                    Aim(nodes[side + "_LowerArm"], nodes[side + "_Hand"], direction);
                }
                var human = new List<HumanBone>();
                for (int i = 0; i < (int)HumanBodyBones.LastBone; i++)
                {
                    string id = ((HumanBodyBones)i).ToString();
                    string sourceName = id;
                    foreach (string side in new[] { "Left", "Right" })
                        if (id.StartsWith(side, StringComparison.Ordinal))
                            sourceName = side + "_" + id.Substring(side.Length).Replace("Little", "Pinky");
                    if (nodes.ContainsKey(sourceName))
                        human.Add(new HumanBone { humanName = HumanTrait.BoneName[i], boneName = sourceName,
                            limit = new HumanLimit { useDefaultValues = true } });
                }
                foreach (HumanBodyBones bone in HumanoidReplay.BoneOrder)
                    if (!human.Any(b => b.humanName == HumanTrait.BoneName[(int)bone]))
                        throw new InvalidDataException("Supplied FBX is missing replay bone " + bone);
                description = new HumanDescription {
                    human = human.ToArray(),
                    skeleton = raw.GetComponentsInChildren<Transform>().Select(t => new SkeletonBone {
                        name = t.name, position = t.localPosition, rotation = t.localRotation, scale = t.localScale
                    }).ToArray(),
                    upperArmTwist = .5f, lowerArmTwist = .5f,
                    upperLegTwist = .5f, lowerLegTwist = .5f,
                    armStretch = .05f, legStretch = .05f, feetSpacing = 0,
                    hasTranslationDoF = false
                };
            }
            finally { UnityEngine.Object.DestroyImmediate(raw); }
            importer.animationType = ModelImporterAnimationType.Human;
            importer.avatarSetup = ModelImporterAvatarSetup.CreateFromThisModel;
            importer.humanDescription = description;
            importer.SaveAndReimport();

            PrepareTexture("Albedo.jpg", false, true);
            PrepareTexture("Normal.jpg", true, false);
            PrepareTexture("MetallicSmoothness.png", false, false);
            string materialPath = Folder + "TripoB9E9.mat";
            var material = AssetDatabase.LoadAssetAtPath<Material>(materialPath);
            if (material == null)
            {
                material = new Material(Shader.Find("Standard"));
                AssetDatabase.CreateAsset(material, materialPath);
            }
            material.mainTexture = AssetDatabase.LoadAssetAtPath<Texture2D>(Folder + "Albedo.jpg");
            material.SetTexture("_BumpMap", AssetDatabase.LoadAssetAtPath<Texture2D>(Folder + "Normal.jpg"));
            material.SetTexture("_MetallicGlossMap", AssetDatabase.LoadAssetAtPath<Texture2D>(Folder + "MetallicSmoothness.png"));
            material.SetFloat("_BumpScale", 1);
            material.SetFloat("_GlossMapScale", 1);
            material.SetFloat("_SmoothnessTextureChannel", 0);
            material.EnableKeyword("_NORMALMAP");
            material.EnableKeyword("_METALLICGLOSSMAP");
            EditorUtility.SetDirty(material);

            var instance = UnityEngine.Object.Instantiate(AssetDatabase.LoadAssetAtPath<GameObject>(ModelPath));
            try
            {
                var animator = instance.GetComponent<Animator>();
                if (animator == null || animator.avatar == null || !animator.avatar.isHuman || !animator.avatar.isValid)
                    throw new InvalidDataException("Tripo explicit Humanoid mapping failed");
                var nodes = instance.GetComponentsInChildren<Transform>().ToDictionary(t => t.name);
                // ModelImporter does not apply Avatar's authored pose to the
                // visible FBX instance; replay captures the visible transforms.
                foreach (var bone in description.skeleton)
                    if (nodes.TryGetValue(bone.name, out Transform node))
                    {
                        node.localPosition = bone.position;
                        node.localRotation = bone.rotation;
                        node.localScale = bone.scale;
                    }
                animator.enabled = false;
                instance.transform.localScale *= 1.48f / animator.GetBoneTransform(HumanBodyBones.Head).position.y;
                instance.name = "Tripo B9E9";
                var skins = instance.GetComponentsInChildren<SkinnedMeshRenderer>();
                foreach (var skin in skins)
                {
                    skin.sharedMaterials = Enumerable.Repeat(material, skin.sharedMaterials.Length).ToArray();
                    skin.updateWhenOffscreen = true;
                    skin.localBounds = new Bounds(Vector3.zero, Vector3.one * 5);
                }
                var replayBones = HumanoidReplay.BoneOrder.Select(animator.GetBoneTransform).ToArray();
                var contact = new AvatarSoleContact(instance.transform, replayBones);
                Directory.CreateDirectory(Path.GetDirectoryName(PrefabPath));
                PrefabUtility.SaveAsPrefabAsset(instance, PrefabPath);
                AssetDatabase.SaveAssets();
                Debug.Log($"DOLLFIGHT_TRIPO_IMPORTED bones={replayBones.Count(b => b != null)}/19 " +
                    $"triangles={skins.Sum(s => s.sharedMesh.triangles.Length / 3)} " +
                    $"head={animator.GetBoneTransform(HumanBodyBones.Head).position.y:F3}m " +
                    $"soleOffset={contact.RestFloorOffset:F4}m; original 4096px textures");
            }
            finally { UnityEngine.Object.DestroyImmediate(instance); }
        }

        static void Aim(Transform joint, Transform child, Vector3 direction)
        {
            joint.rotation = Quaternion.FromToRotation(child.position - joint.position, direction) * joint.rotation;
        }

        static void VerifySourceCoordinates(Dictionary<string, Transform> nodes)
        {
            if (!(nodes["Left_UpperArm"].position.x < nodes["Right_UpperArm"].position.x) ||
                !(nodes["Left_Toes"].position.z > nodes["Left_Foot"].position.z))
                throw new InvalidDataException("FBX axes differ from the inspected +Z-facing Unity coordinate convention");
        }

        static void PrepareTexture(string filename, bool normal, bool srgb)
        {
            var texture = (TextureImporter)AssetImporter.GetAtPath(Folder + filename);
            if (texture == null) throw new FileNotFoundException("Missing supplied/packed texture", filename);
            texture.textureType = normal ? TextureImporterType.NormalMap : TextureImporterType.Default;
            texture.sRGBTexture = srgb;
            texture.maxTextureSize = 8192;
            texture.textureCompression = TextureImporterCompression.CompressedHQ;
            if (!normal) texture.alphaSource = TextureImporterAlphaSource.FromInput;
            texture.SaveAndReimport();
        }
    }
}
