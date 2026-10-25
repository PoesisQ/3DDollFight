using System;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEngine;

namespace DollFight.Editor
{
    public static class TeamCharacterImport
    {
        const string Folder = "Assets/Art/TeamCharacter/";

        [MenuItem("DollFight/Prepare Team Character")]
        public static void Prepare()
        {
            var importer = (ModelImporter)AssetImporter.GetAtPath(Folder + "TeamCharacter.fbx");
            if (importer == null) throw new FileNotFoundException("Team FBX is missing");
            importer.animationType = ModelImporterAnimationType.Human;
            importer.avatarSetup = ModelImporterAvatarSetup.CreateFromThisModel;
            importer.importAnimation = false;
            importer.isReadable = true;
            importer.SaveAndReimport();
            foreach (string texture in new[] { "Albedo.jpg", "Normal.png" })
            {
                var ti = (TextureImporter)AssetImporter.GetAtPath(Folder + texture);
                ti.textureType = texture.StartsWith("Normal") ? TextureImporterType.NormalMap : TextureImporterType.Default;
                ti.maxTextureSize = 8192; // Keep the supplied texture resolution.
                ti.textureCompression = TextureImporterCompression.CompressedHQ;
                ti.SaveAndReimport();
            }
            string materialPath = Folder + "TeamCharacter.mat";
            var material = AssetDatabase.LoadAssetAtPath<Material>(materialPath);
            if (material == null)
            {
                material = new Material(Shader.Find("Standard"));
                AssetDatabase.CreateAsset(material, materialPath);
            }
            material.mainTexture = AssetDatabase.LoadAssetAtPath<Texture2D>(Folder + "Albedo.jpg");
            material.SetTexture("_BumpMap", AssetDatabase.LoadAssetAtPath<Texture2D>(Folder + "Normal.png"));
            material.SetFloat("_BumpScale", 0.45f);
            material.SetFloat("_Glossiness", 0.18f);
            material.EnableKeyword("_NORMALMAP");
            EditorUtility.SetDirty(material);

            var source = AssetDatabase.LoadAssetAtPath<GameObject>(Folder + "TeamCharacter.fbx");
            var instance = UnityEngine.Object.Instantiate(source);
            instance.name = "Team Character";
            try
            {
                var animator = instance.GetComponent<Animator>();
                if (animator == null || !animator.avatar.isHuman || !animator.avatar.isValid)
                    throw new InvalidDataException("FBX failed Humanoid mapping");
                // ModelImporter computes a valid T-pose for the Avatar, but the
                // instantiated FBX still has its original A-pose. Apply that
                // authored Avatar skeleton before capturing delta-rotation binds.
                var nodes = instance.GetComponentsInChildren<Transform>().ToDictionary(t => t.name);
                foreach (var bone in importer.humanDescription.skeleton)
                    if (nodes.TryGetValue(bone.name, out Transform node))
                    {
                        node.localPosition = bone.position;
                        node.localRotation = bone.rotation;
                        node.localScale = bone.scale;
                    }
                animator.enabled = false;
                float headHeight = animator.GetBoneTransform(HumanBodyBones.Head).position.y;
                instance.transform.localScale *= 1.48f / headHeight;
                foreach (var skin in instance.GetComponentsInChildren<SkinnedMeshRenderer>())
                {
                    skin.sharedMaterials = Enumerable.Repeat(material, skin.sharedMaterials.Length).ToArray();
                    skin.updateWhenOffscreen = true;
                    skin.localBounds = new Bounds(Vector3.zero, Vector3.one * 5);
                }
                Directory.CreateDirectory("Assets/Resources");
                PrefabUtility.SaveAsPrefabAsset(instance, "Assets/Resources/TeamCharacter.prefab");
                AssetDatabase.SaveAssets();
                Debug.Log("DOLLFIGHT_TEAM_IMPORTED valid Humanoid, T-pose, 12200 triangles, original textures");
            }
            finally { UnityEngine.Object.DestroyImmediate(instance); }
        }
    }
}
