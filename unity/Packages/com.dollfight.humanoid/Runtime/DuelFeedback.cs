using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using UnityEngine;

namespace DollFight
{
    [Serializable]
    public sealed class DuelContact
    {
        public string id;
        public float time;
        public int round, attacker, defender;
        public string action, outcome, label;
        public float damage;
        public int comboCount;
        public bool counter;
        // Same canonical stage coordinates as DuelCapsule; convert at presentation.
        public Vector3 position;
    }

    // Only this component consumes contacts. Rendering any number of cameras or
    // IMGUI passes never creates another sound, impulse, or gameplay event.
    public sealed class DuelFeedback : MonoBehaviour
    {
        public bool soundEnabled = true, shakeEnabled = true, hapticsEnabled = true;
        // Explicit diagnostic opt-in; normal gameplay still pauses feedback on focus loss.
        public bool ignoreApplicationFocus;
        [Range(0, 1)] public float volume = 0.7f;
        [Range(0, 1.5f)] public float intensity = 1;
        public DuelContact LastContact { get; private set; }
        public float ContactAge => LastContact == null ? float.PositiveInfinity : (float)Math.Max(0, Now - lastContactAt);

        const int VoiceCount = 12;
        readonly HashSet<string> consumed = new HashSet<string>(StringComparer.Ordinal);
        readonly List<Pulse> pulses = new List<Pulse>(16);
        readonly List<PendingContact> pending = new List<PendingContact>(8);
        // A clock seam permits deterministic boundary tests without changing Unity time.
        Func<double> clock = () => Time.realtimeSinceStartupAsDouble;
        double Now => clock();
        double lastContactAt, stopFrom, stopUntil, lastPlaybackSample = double.NaN;
        double vibrationUntil;
        float vibrationPower;
        bool focused = true, applicationPaused, activePlayback;
        Camera targetCamera, shakenCamera;
        Vector3 appliedPosition;
        Quaternion appliedRotation = Quaternion.identity;
        Texture2D ring, glow, slash;
        Font font;
        GUIStyle impactText;
        AudioClip[] clips, sampledClips;
        AudioSource[] voices;
        double[] voiceUntil;
        int nextVoice;

        struct PendingContact
        {
            public DuelContact contact;
            public int index;
        }

        struct Pulse
        {
            public DuelContact contact;
            public double started;
            public float power, seed, lifetime;
            public Color color;
            public int kind;
            public string damageText;
        }

        public void Initialize(Camera camera, Shader shader)
        {
            // GUI textures intentionally do not depend on a shader surviving build stripping.
            if (targetCamera != camera && shakenCamera != null) RestoreCamera(shakenCamera);
            targetCamera = camera;
            if (ring == null) ring = MakeTexture(true);
            if (glow == null) glow = MakeTexture(false);
            if (slash == null) slash = MakeSlashTexture();
            if (Application.isPlaying && clips == null) CreateAudio();
        }

        public void ResetAt(float time, DuelContact[] contacts)
        {
            ClearTransient();
            consumed.Clear();
            if (contacts == null) return;
            for (int i = 0; i < contacts.Length; i++)
                if (contacts[i] != null && contacts[i].time <= time)
                    consumed.Add(ContactKey(contacts[i], i));
        }

        public void Advance(float previousTime, float currentTime, DuelContact[] contacts, bool playing)
        {
            if (!float.IsFinite(previousTime) || !float.IsFinite(currentTime)) return;
            if (currentTime < previousTime)
            {
                ResetAt(currentTime, contacts);
                return;
            }
            if (!playing || !focused || applicationPaused || !isActiveAndEnabled)
            {
                // Also mark the paused interval consumed, so resuming does not replay
                // contacts that passed while the application was unfocused.
                ClearTransient();
                MarkThrough(currentTime, contacts);
                return;
            }
            activePlayback = true;
            UpdateSettings();
            if (contacts == null || currentTime <= previousTime) return;
            pending.Clear();
            for (int i = 0; i < contacts.Length; i++)
            {
                var contact = contacts[i];
                if (contact == null || !float.IsFinite(contact.time) || contact.time <= previousTime || contact.time > currentTime) continue;
                if (consumed.Add(ContactKey(contact, i))) pending.Add(new PendingContact { contact = contact, index = i });
            }
            // Exported arrays are ordered, but chronological feedback remains correct
            // for hand-authored timelines and bidirectional contacts at the same time.
            pending.Sort((a, b) => a.contact.time != b.contact.time
                ? a.contact.time.CompareTo(b.contact.time) : a.index.CompareTo(b.index));
            foreach (var item in pending)
                if (IsImpact(item.contact.outcome)) Emit(item.contact);
            pending.Clear();
        }

        public float PlaybackDelta(float delta)
        {
            if (!float.IsFinite(delta) || delta <= 0) return 0;
            double now = Now;
            double previous = double.IsNaN(lastPlaybackSample) ? now : lastPlaybackSample;
            lastPlaybackSample = now;
            if (!focused || applicationPaused || !isActiveAndEnabled) return 0;
            if (!activePlayback || stopUntil <= previous) return delta;
            double elapsed = now - previous;
            if (elapsed <= 0.000001) return now < stopUntil ? 0 : delta;
            double stopped = Math.Max(0, Math.Min(now, stopUntil) - Math.Max(previous, stopFrom));
            return delta * (float)Math.Max(0, 1 - stopped / elapsed);
        }

        // Remove only the transform contribution owned by this component. External
        // camera motion between Apply and Restore is preserved, including world rotation.
        public void RestoreCamera(Camera camera)
        {
            if (camera == null || camera != shakenCamera) return;
            camera.transform.position -= appliedPosition;
            camera.transform.rotation *= Quaternion.Inverse(appliedRotation);
            shakenCamera = null;
            appliedPosition = Vector3.zero;
            appliedRotation = Quaternion.identity;
        }

        public void ApplyCamera(Camera camera)
        {
            if (shakenCamera != null) RestoreCamera(shakenCamera);
            if (camera == null || !shakeEnabled || !activePlayback || !focused || applicationPaused || intensity <= 0) return;
            float horizontal = 0, vertical = 0, roll = 0;
            double now = Now;
            foreach (var pulse in pulses)
            {
                float age = (float)(now - pulse.started);
                if (age < 0 || age > 0.32f) continue;
                float envelope = Mathf.Pow(1 - age / 0.32f, 2) * pulse.power;
                float sign = pulse.contact.attacker == 0 ? 1 : -1;
                horizontal += sign * Mathf.Cos(age * 78 + pulse.seed) * envelope;
                vertical += Mathf.Sin(age * 101 + pulse.seed) * envelope * 0.55f;
                roll += sign * Mathf.Sin(age * 58 + pulse.seed) * envelope;
            }
            float strength = Mathf.Clamp(intensity, 0, 1.5f);
            horizontal = Mathf.Clamp(horizontal, -1.5f, 1.5f) * strength;
            vertical = Mathf.Clamp(vertical, -1.5f, 1.5f) * strength;
            appliedPosition = camera.transform.right * (horizontal * 0.021f) + camera.transform.up * (vertical * 0.016f);
            appliedRotation = Quaternion.Euler(vertical * 0.48f, horizontal * 0.4f, Mathf.Clamp(roll, -1.5f, 1.5f) * strength * 0.6f);
            camera.transform.position += appliedPosition;
            camera.transform.rotation *= appliedRotation;
            shakenCamera = camera;
        }

        public void DrawOverlay(Rect arenaPixels)
        {
            if (Event.current == null || Event.current.type != EventType.Repaint || targetCamera == null || ring == null ||
                !activePlayback || !focused || applicationPaused || arenaPixels.width <= 0 || arenaPixels.height <= 0 || intensity <= 0) return;
            var oldMatrix = GUI.matrix;
            var oldColor = GUI.color;
            GUI.matrix = Matrix4x4.identity;
            GUI.BeginGroup(arenaPixels);
            try
            {
                EnsureTextStyles();
                float scale = Mathf.Min(arenaPixels.width / 1280f, arenaPixels.height / 720f);
                float strength = Mathf.Clamp(intensity, 0, 1.5f);
                double now = Now;
                foreach (var pulse in pulses)
                {
                    float age = (float)(now - pulse.started);
                    if (age < 0 || age > pulse.lifetime) continue;
                    Vector3 viewport = targetCamera.WorldToViewportPoint(HumanoidReplay.StageToUnity(pulse.contact.position));
                    if (viewport.z <= 0 || viewport.x < 0 || viewport.x > 1 || viewport.y < 0 || viewport.y > 1) continue;
                    Vector2 center = new Vector2(viewport.x * arenaPixels.width, (1 - viewport.y) * arenaPixels.height);
                    float progress = age / pulse.lifetime;
                    float fade = Mathf.Pow(1 - progress, 1.7f);
                    Color color = pulse.color;
                    if (pulse.kind == 1 || pulse.kind == 2)
                        DrawGuard(pulse, center, age, scale, strength);
                    else
                        DrawStrike(pulse, center, age, scale, strength);

                    // The HUD owns contact names, counters and combo totals. Only a small,
                    // preformatted damage number floats away from the actual contact.
                    if (pulse.damageText == null) continue;
                    float side = pulse.contact.defender == 0 ? -1 : 1;
                    float lane = pulse.contact.defender == 0 ? -36 : -14;
                    float pop = 1 + 0.2f * Mathf.Clamp01(1 - age / 0.09f);
                    Rect labelRect = new Rect(center.x + side * (35 + age * 16) * scale - 36 * scale,
                        center.y + (lane - age * 38) * scale, 72 * scale, 30 * scale);
                    impactText.fontSize = Mathf.Max(9, Mathf.RoundToInt((pulse.kind == 3 ? 23 : 19) * scale * pop));
                    GUI.color = new Color(0.025f, 0.035f, 0.055f, fade * strength);
                    GUI.Label(new Rect(labelRect.x + scale, labelRect.y + 2 * scale, labelRect.width, labelRect.height), pulse.damageText, impactText);
                    GUI.color = Color.Lerp(color, new Color(1, 0.97f, 0.86f), 0.8f);
                    GUI.color = new Color(GUI.color.r, GUI.color.g, GUI.color.b, fade * strength);
                    GUI.Label(labelRect, pulse.damageText, impactText);
                }
            }
            finally
            {
                GUI.EndGroup();
                GUI.matrix = oldMatrix;
                GUI.color = oldColor;
            }
        }

        void DrawStrike(Pulse pulse, Vector2 center, float age, float scale, float strength)
        {
            float burst = Mathf.Clamp01(1 - age / 0.25f);
            float travel = Mathf.Sqrt(Mathf.Clamp01(age / 0.25f));
            float heavy = pulse.kind == 3 ? 1.28f : Mathf.Lerp(0.88f, 1.12f, pulse.power);
            float sign = pulse.contact.attacker == 0 ? 1 : -1;
            float angle = (sign > 0 ? -24 : 204) + Mathf.Sin(pulse.seed) * 13;
            Vector2 axis = Direction(angle * Mathf.Deg2Rad);
            Vector2 slashCenter = center + axis * travel * 17 * scale;
            // Separate colored, white-hot and opposing cuts give a jagged layered burst.
            // Every texture is generated once; these draws do not allocate meshes or pixels.
            float length = (94 + travel * 68) * scale * heavy;
            float width = (14 + burst * 13) * scale * heavy;
            GUI.color = WithAlpha(pulse.color, burst * 0.76f * strength);
            DrawSlash(slashCenter, length, width, angle);
            DrawSlash(center - axis * 7 * scale, length * 0.68f, width * 0.52f, angle + 72);
            GUI.color = new Color(1, 0.96f, 0.84f, burst * 0.94f * strength);
            DrawSlash(slashCenter, length * 0.77f, width * 0.3f, angle - 2);
            DrawSlash(center, length * 0.38f, width * 0.31f, angle + 72);

            float flash = Mathf.Clamp01(1 - age / 0.12f);
            float size = (pulse.kind == 3 ? 86 : 62) * scale;
            GUI.color = WithAlpha(pulse.color, flash * 0.7f * strength);
            GUI.DrawTexture(new Rect(center.x - size, center.y - size, size * 2, size * 2), glow);
            GUI.color = new Color(1, 0.98f, 0.9f, flash * strength);
            GUI.DrawTexture(new Rect(center.x - size * 0.42f, center.y - size * 0.42f, size * 0.84f, size * 0.84f), glow);
            DrawFlecks(pulse, center, age, scale, strength, pulse.kind == 3 ? 13 : 9);
            if (pulse.kind == 3)
            {
                float radius = (24 + travel * 84) * scale;
                GUI.color = WithAlpha(pulse.color, burst * 0.54f * strength);
                GUI.DrawTexture(new Rect(center.x - radius, center.y - radius, radius * 2, radius * 2), ring);
            }
        }

        void DrawGuard(Pulse pulse, Vector2 center, float age, float scale, float strength)
        {
            bool parry = pulse.kind == 2;
            float progress = Mathf.Clamp01(age / (parry ? 0.32f : 0.25f));
            float fade = (1 - progress) * (1 - progress);
            float radius = (18 + Mathf.Sqrt(progress) * (parry ? 62 : 45)) * scale;
            GUI.color = WithAlpha(pulse.color, fade * 0.95f * strength);
            GUI.DrawTexture(new Rect(center.x - radius, center.y - radius, radius * 2, radius * 2), ring);
            if (parry)
            {
                GUI.color = new Color(0.91f, 1, 0.95f, fade * strength);
                float inner = radius * 0.72f;
                GUI.DrawTexture(new Rect(center.x - inner, center.y - inner, inner * 2, inner * 2), ring);
                DrawSlash(center, (65 + progress * 32) * scale, 5 * scale, -42);
            }
            float flash = Mathf.Clamp01(1 - age / 0.1f);
            float size = (parry ? 62 : 42) * scale;
            GUI.color = WithAlpha(pulse.color, flash * 0.8f * strength);
            GUI.DrawTexture(new Rect(center.x - size / 2, center.y - size / 2, size, size), glow);
            DrawFlecks(pulse, center, age, scale, strength * 0.7f, parry ? 8 : 5);
        }

        static void DrawFlecks(Pulse pulse, Vector2 center, float age, float scale, float strength, int count)
        {
            float life = pulse.kind == 3 ? 0.46f : 0.36f;
            float fade = Mathf.Clamp01(1 - age / life);
            float sign = pulse.contact.attacker == 0 ? 1 : -1;
            for (int i = 0; i < count; i++)
            {
                float angle = i * 2.399963f + pulse.seed;
                Vector2 direction = Direction(angle);
                // A forward bias sells the direction without obscuring the defender's face.
                direction.x += sign * 0.55f;
                direction.Normalize();
                float speed = 135 + (i % 4) * 41;
                Vector2 position = center + direction * (15 + age * speed) * scale + Vector2.down * age * age * 150 * scale;
                GUI.color = i % 3 == 0 ? new Color(1, 0.96f, 0.82f, fade * strength) : WithAlpha(pulse.color, fade * strength);
                DrawLine(position, position + direction * (3 + (i % 3) * 3) * fade * scale, (i % 3 == 0 ? 2.4f : 1.5f) * scale);
            }
        }

        void DrawSlash(Vector2 center, float length, float width, float angle)
        {
            Matrix4x4 matrix = GUI.matrix;
            GUIUtility.RotateAroundPivot(angle, center);
            GUI.DrawTexture(new Rect(center.x - length / 2, center.y - width / 2, length, width), slash);
            GUI.matrix = matrix;
        }

        static Vector2 Direction(float radians) => new Vector2(Mathf.Cos(radians), Mathf.Sin(radians));
        static Color WithAlpha(Color color, float alpha) => new Color(color.r, color.g, color.b, Mathf.Clamp01(alpha));

        void Emit(DuelContact contact)
        {
            int kind = contact.outcome == "block" ? 1 : contact.outcome == "parry" ? 2 : contact.outcome == "guard_break" ? 3 : 0;
            bool heavy = contact.damage >= 12 || (contact.action != null && contact.action.IndexOf("kick", StringComparison.OrdinalIgnoreCase) >= 0);
            float power = kind == 1 ? 0.3f : kind == 2 ? 0.52f : kind == 3 ? 1.2f : heavy ? 0.95f : 0.65f;
            Color color = kind == 1 ? new Color(0.35f, 0.69f, 1) : kind == 2 ? new Color(0.46f, 1, 0.77f) :
                kind == 3 ? new Color(1, 0.76f, 0.22f) : contact.attacker == 0 ? new Color(243 / 255f, 56 / 255f, 157 / 255f) : new Color(64 / 255f, 207 / 255f, 1);
            double now = Now;
            LastContact = contact;
            lastContactAt = now;
            pulses.Add(new Pulse { contact = contact, started = now, power = power, kind = kind,
                lifetime = kind == 3 ? 0.7f : 0.54f, color = color, seed = StableSeed(contact.id),
                damageText = contact.damage > 0 ? "−" + contact.damage.ToString("0.#") : null });
            float strength = Mathf.Clamp(intensity, 0, 1.5f);
            if (strength > 0)
            {
                float pause = kind == 1 ? 0.04f : kind == 2 ? 0.05f : kind == 3 ? 0.075f : heavy ? 0.065f : 0.045f;
                if (stopUntil <= now) stopFrom = now;
                stopUntil = Math.Max(stopUntil, now + pause * Mathf.Min(1, strength));
                if (hapticsEnabled)
                {
                    vibrationPower = Mathf.Max(vibrationPower, power * strength * 0.6f);
                    vibrationUntil = Math.Max(vibrationUntil, now + (kind == 3 ? 0.17 : 0.1));
                    DuelGamepad.Set(vibrationPower * 0.7f, vibrationPower);
                }
            }
            if (soundEnabled && volume > 0 && clips != null && voices != null)
            {
                int sound = kind == 0 ? (heavy ? 1 : 0) : kind + 1;
                float pitch = 0.96f + StableSeed(contact.id + "audio") / (Mathf.PI * 2) * 0.08f;
                float pan = targetCamera == null ? 0 : Mathf.Clamp((targetCamera.WorldToViewportPoint(
                    HumanoidReplay.StageToUnity(contact.position)).x - 0.5f) * 1.2f, -0.6f, 0.6f);
                AudioClip sample = sampledClips == null ? null : sampledClips[sound];
                if (sample != null)
                {
                    PlayVoice(sample, pitch, kind == 1 ? 0.58f : kind == 2 ? 0.62f : 0.88f, pan, now);
                    PlayVoice(clips[sound], pitch, kind == 1 || kind == 2 ? 0.14f : 0.3f, pan, now);
                }
                else PlayVoice(clips[sound], pitch, kind == 1 ? 0.65f : 0.95f, pan, now);
            }
        }

        void PlayVoice(AudioClip clip, float pitch, float gain, float pan, double now)
        {
            AudioSource voice = voices[ReserveVoice(clip, pitch, now)];
            voice.clip = clip;
            voice.volume = Mathf.Clamp01(volume) * gain;
            voice.pitch = pitch;
            voice.panStereo = pan;
            voice.Play();
        }

        int ReserveVoice(AudioClip clip, float pitch, double now)
        {
            int chosen = -1;
            for (int i = 0; i < voices.Length; i++)
            {
                int candidate = (nextVoice + i) % voices.Length;
                // isPlaying alone can still be false before the DSP thread begins
                // the first sound. Reserve immediately so same-frame hits stay layered.
                if (voiceUntil[candidate] <= now && !voices[candidate].isPlaying) { chosen = candidate; break; }
            }
            if (chosen < 0)
            {
                chosen = 0;
                for (int i = 1; i < voices.Length; i++) if (voiceUntil[i] < voiceUntil[chosen]) chosen = i;
            }
            nextVoice = (chosen + 1) % voices.Length;
            voiceUntil[chosen] = now + clip.length / Mathf.Max(0.01f, pitch);
            return chosen;
        }

        void Update()
        {
            UpdateSettings();
            double now = Now;
            for (int i = pulses.Count - 1; i >= 0; i--)
                if (now - pulses[i].started > pulses[i].lifetime) pulses.RemoveAt(i);
            if (vibrationPower > 0 && now >= vibrationUntil) StopVibration();
        }

        void UpdateSettings()
        {
            if (!soundEnabled && voices != null)
                foreach (var voice in voices) if (voice != null && voice.isPlaying) voice.Stop();
            if (!hapticsEnabled || intensity <= 0) StopVibration();
            if (!shakeEnabled && shakenCamera != null) RestoreCamera(shakenCamera);
            if (intensity <= 0) stopFrom = stopUntil = 0;
        }

        void MarkThrough(float time, DuelContact[] contacts)
        {
            if (contacts == null) return;
            for (int i = 0; i < contacts.Length; i++)
                if (contacts[i] != null && contacts[i].time <= time) consumed.Add(ContactKey(contacts[i], i));
        }

        void ClearTransient()
        {
            activePlayback = false;
            pulses.Clear();
            pending.Clear();
            LastContact = null;
            stopFrom = stopUntil = 0;
            lastPlaybackSample = double.NaN;
            if (shakenCamera != null) RestoreCamera(shakenCamera);
            if (voices != null) foreach (var voice in voices) if (voice != null) voice.Stop();
            if (voiceUntil != null) Array.Clear(voiceUntil, 0, voiceUntil.Length);
            nextVoice = 0;
            StopVibration();
        }

        void StopVibration()
        {
            if (vibrationPower > 0) DuelGamepad.Set(0, 0);
            vibrationPower = 0;
            vibrationUntil = 0;
        }

        void OnApplicationFocus(bool hasFocus) { focused = hasFocus || ignoreApplicationFocus; if (!focused) ClearTransient(); }
        void OnApplicationPause(bool paused) { applicationPaused = paused; if (paused) ClearTransient(); }
        void OnDisable() { ClearTransient(); }
        void OnApplicationQuit() { ClearTransient(); }
        void OnDestroy()
        {
            ClearTransient();
            if (voices != null) foreach (var voice in voices) Release(voice);
            if (clips != null) foreach (var clip in clips) Release(clip);
            // sampledClips are borrowed Resources assets shared by other instances.
            // Only the procedural clips in clips belong to this component.
            Release(ring); Release(glow); Release(slash); Release(font);
        }

        static void Release(UnityEngine.Object resource)
        {
            if (resource == null) return;
            if (Application.isPlaying) Destroy(resource); else DestroyImmediate(resource);
        }

        static bool IsImpact(string outcome) => outcome == "hit" || outcome == "guard_break" || outcome == "block" || outcome == "parry";
        static string ContactKey(DuelContact contact, int index) => !string.IsNullOrEmpty(contact.id) ? contact.id : "legacy:" + index;
        static float StableSeed(string id)
        {
            uint hash = 2166136261;
            if (id != null) foreach (char character in id) hash = unchecked((hash ^ character) * 16777619);
            return (hash % 10000) / 10000f * Mathf.PI * 2;
        }

        void EnsureTextStyles()
        {
            if (impactText != null) return;
            font = Font.CreateDynamicFontFromOSFont(new[] { "Microsoft YaHei", "Arial" }, 22);
            impactText = new GUIStyle(GUI.skin.label) { font = font, fontStyle = FontStyle.Bold, alignment = TextAnchor.MiddleCenter };
        }

        static void DrawLine(Vector2 from, Vector2 to, float width)
        {
            Vector2 delta = to - from;
            Matrix4x4 matrix = GUI.matrix;
            GUIUtility.RotateAroundPivot(Mathf.Atan2(delta.y, delta.x) * Mathf.Rad2Deg, from);
            GUI.DrawTexture(new Rect(from.x, from.y - width / 2, delta.magnitude, width), Texture2D.whiteTexture);
            GUI.matrix = matrix;
        }

        static Texture2D MakeTexture(bool isRing)
        {
            const int size = 128;
            var texture = new Texture2D(size, size, TextureFormat.RGBA32, false) {
                name = isRing ? "Duel impact ring" : "Duel impact glow", hideFlags = HideFlags.HideAndDontSave,
                filterMode = FilterMode.Bilinear, wrapMode = TextureWrapMode.Clamp
            };
            var pixels = new Color[size * size];
            for (int y = 0; y < size; y++)
                for (int x = 0; x < size; x++)
                {
                    float distance = new Vector2((x + 0.5f) / size * 2 - 1, (y + 0.5f) / size * 2 - 1).magnitude;
                    float alpha = isRing ? Mathf.Exp(-Mathf.Pow((distance - 0.81f) / 0.037f, 2)) :
                        Mathf.Pow(Mathf.Max(0, 1 - distance), 3);
                    pixels[y * size + x] = new Color(1, 1, 1, alpha);
                }
            texture.SetPixels(pixels); texture.Apply(false, true);
            return texture;
        }

        static Texture2D MakeSlashTexture()
        {
            const int width = 256, height = 64;
            var texture = new Texture2D(width, height, TextureFormat.RGBA32, false) {
                name = "Duel jagged impact slash", hideFlags = HideFlags.HideAndDontSave,
                filterMode = FilterMode.Bilinear, wrapMode = TextureWrapMode.Clamp
            };
            // Deliberately uneven silhouette: pointed ends, two sharp notches and a
            // broad paint-like middle. Rasterize only during Initialize.
            Vector2[] outline = {
                new Vector2(0.01f, 0.58f), new Vector2(0.36f, 0.37f), new Vector2(0.29f, 0.24f),
                new Vector2(0.55f, 0.34f), new Vector2(0.91f, 0.08f), new Vector2(0.74f, 0.43f),
                new Vector2(0.99f, 0.42f), new Vector2(0.63f, 0.65f), new Vector2(0.73f, 0.79f),
                new Vector2(0.48f, 0.7f), new Vector2(0.18f, 0.94f), new Vector2(0.32f, 0.64f)
            };
            var pixels = new Color32[width * height];
            for (int y = 0; y < height; y++)
                for (int x = 0; x < width; x++)
                {
                    float px = (x + 0.5f) / width, py = (y + 0.5f) / height;
                    bool inside = false;
                    for (int i = 0, j = outline.Length - 1; i < outline.Length; j = i++)
                        if ((outline[i].y > py) != (outline[j].y > py) &&
                            px < (outline[j].x - outline[i].x) * (py - outline[i].y) / (outline[j].y - outline[i].y) + outline[i].x)
                            inside = !inside;
                    pixels[y * width + x] = new Color32(255, 255, 255, inside ? (byte)255 : (byte)0);
                }
            texture.SetPixels32(pixels); texture.Apply(false, true);
            return texture;
        }

        void CreateAudio()
        {
            clips = new AudioClip[5];
            for (int kind = 0; kind < clips.Length; kind++) clips[kind] = MakeClip(kind);
            sampledClips = new[] {
                Resources.Load<AudioClip>("DollFight/Audio/impactPunch_medium_000"),
                Resources.Load<AudioClip>("DollFight/Audio/impactPunch_heavy_001"),
                Resources.Load<AudioClip>("DollFight/Audio/impactMetal_light_002"),
                Resources.Load<AudioClip>("DollFight/Audio/impactBell_heavy_004"),
                Resources.Load<AudioClip>("DollFight/Audio/impactGlass_heavy_000")
            };
            voices = new AudioSource[VoiceCount];
            voiceUntil = new double[VoiceCount];
            for (int i = 0; i < voices.Length; i++)
            {
                var voice = gameObject.AddComponent<AudioSource>();
                voice.playOnAwake = false;
                voice.loop = false;
                voice.spatialBlend = 0;
                voice.dopplerLevel = 0;
                voice.priority = 64;
                voices[i] = voice;
            }
        }

        static AudioClip MakeClip(int kind)
        {
            const int rate = 44100;
            bool metal = kind == 2 || kind == 3;
            float length = kind == 1 || kind == 4 ? 0.3f : metal ? 0.22f : 0.19f;
            var samples = new float[Mathf.CeilToInt(rate * length)];
            uint noiseState = (uint)(8471 + kind * 113);
            float phase = 0, filteredNoise = 0;
            for (int i = 0; i < samples.Length; i++)
            {
                float t = i / (float)rate;
                noiseState ^= noiseState << 13; noiseState ^= noiseState >> 17; noiseState ^= noiseState << 5;
                float noise = (noiseState & 65535) / 32767.5f - 1;
                filteredNoise = Mathf.Lerp(filteredNoise, noise, 0.19f);
                float attack = Mathf.Min(1, t / 0.0018f);
                float tail = Mathf.Clamp01((length - t) / 0.025f);
                float sample;
                if (metal)
                {
                    float baseHz = kind == 3 ? 1130 : 870;
                    sample = (Mathf.Sin(t * baseHz * Mathf.PI * 2) +
                        0.48f * Mathf.Sin(t * baseHz * 1.47f * Mathf.PI * 2) +
                        0.26f * Mathf.Sin(t * baseHz * 2.19f * Mathf.PI * 2)) * Mathf.Exp(-t * (kind == 3 ? 24 : 34)) * 0.27f;
                    sample += noise * Mathf.Exp(-t * 150) * 0.32f + filteredNoise * Mathf.Exp(-t * 50) * 0.13f;
                }
                else
                {
                    float bass = kind == 0 ? 105 : kind == 4 ? 67 : 73;
                    phase += (bass + 150 * Mathf.Exp(-t * 55)) * Mathf.PI * 2 / rate;
                    sample = Mathf.Sin(phase) * Mathf.Exp(-t * (kind == 0 ? 25 : 19)) * 0.6f;
                    sample += filteredNoise * Mathf.Exp(-t * 40) * 0.7f + noise * Mathf.Exp(-t * 190) * 0.36f;
                    if (kind == 4) sample += Mathf.Sin(t * 620 * Mathf.PI * 2) * Mathf.Exp(-t * 30) * 0.18f;
                }
                samples[i] = Mathf.Clamp(sample * attack * tail, -0.95f, 0.95f);
            }
            var clip = AudioClip.Create("Duel " + new[] { "light impact", "heavy impact", "guard", "parry", "guard break" }[kind], samples.Length, 1, rate, false);
            clip.hideFlags = HideFlags.HideAndDontSave;
            clip.SetData(samples, 0);
            return clip;
        }
    }

    // Optional XInput backend. Unsupported platforms, missing DLLs and unplugged
    // controllers are silent; there is no package or input-system dependency.
    static class DuelGamepad
    {
#if UNITY_STANDALONE_WIN || UNITY_EDITOR_WIN
        [StructLayout(LayoutKind.Sequential)]
        struct Vibration { public ushort leftMotorSpeed, rightMotorSpeed; }
        [DllImport("xinput1_4.dll", EntryPoint = "XInputSetState")]
        static extern uint Set14(uint userIndex, ref Vibration vibration);
        [DllImport("xinput9_1_0.dll", EntryPoint = "XInputSetState")]
        static extern uint SetLegacy(uint userIndex, ref Vibration vibration);
        static int backend;
#endif
        public static void Set(float left, float right)
        {
#if UNITY_STANDALONE_WIN || UNITY_EDITOR_WIN
            if (backend < 0) return;
            var vibration = new Vibration { leftMotorSpeed = (ushort)(Mathf.Clamp01(left) * 65535), rightMotorSpeed = (ushort)(Mathf.Clamp01(right) * 65535) };
            try
            {
                for (uint controller = 0; controller < 4; controller++)
                {
                    if (backend == 2) SetLegacy(controller, ref vibration);
                    else
                    {
                        try { Set14(controller, ref vibration); backend = 1; }
                        catch (DllNotFoundException) { backend = 2; SetLegacy(controller, ref vibration); }
                        catch (EntryPointNotFoundException) { backend = 2; SetLegacy(controller, ref vibration); }
                    }
                }
            }
            catch (DllNotFoundException) { backend = -1; }
            catch (EntryPointNotFoundException) { backend = -1; }
            catch (BadImageFormatException) { backend = -1; }
#endif
        }
    }
}
