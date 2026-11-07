using System;
using System.Collections.Generic;
using UnityEngine;

namespace DollFight
{
    /// <summary>Native, resolution-independent local-versus lobby. Draft choices never mutate a running match.</summary>
    [DefaultExecutionOrder(14000)]
    public sealed class DuelSelectionScreen : MonoBehaviour
    {
        static readonly Color Paper = new Color(.98f, .96f, .9f);
        static readonly Color Muted = new Color(.66f, .62f, .75f);
        static readonly Color Pink = new Color(1, .19f, .57f);
        static readonly Color Cyan = new Color(.22f, .89f, 1);
        static readonly Color Acid = new Color(.89f, 1, .28f);
        static readonly Color Ink = new Color(.055f, .025f, .105f);
        const float CanvasWidth = 1920, CanvasHeight = 1080;
        readonly int[] picks = { 0, 1 };
        readonly bool[] confirmed = new bool[2];
        readonly float[] selectionTime = new float[2];
        readonly Dictionary<string, Texture> stageImages = new Dictionary<string, Texture>(StringComparer.Ordinal);
        DollFightDemo demo;
        CharacterCatalog catalog;
        SelectionPortraits portraits;
        Font fallback, display, technical;
        GUIStyle style;
        Texture2D backdrop, fade;
        int page, activePlayer, stageIndex;
        float openedAt, stageChangedAt;
        bool initialized;

        public bool IsOpen { get; private set; }
        public bool CharactersPage => page == 0;
        public int ActivePlayer => activePlayer;
        public string SelectedStageId => StageCatalog.All[stageIndex].id;
        public bool PortraitsReady => portraits != null && portraits.Ready;
        public string PortraitError => portraits != null ? portraits.Error : null;
        public string SelectedCharacterId(int player) { ValidatePlayer(player); return catalog.Characters[picks[player]].id; }
        public bool PlayerConfirmed(int player) { ValidatePlayer(player); return confirmed[player]; }

        public void Initialize(DollFightDemo owner)
        {
            if (initialized) return;
            demo = owner != null ? owner : throw new ArgumentNullException(nameof(owner));
            catalog = demo.Catalog ?? CharacterCatalog.Load();
            for (int p = 0; p < 2; p++)
            {
                string id = demo.SelectedCharacter(p).id;
                picks[p] = IndexOfCharacter(id);
            }
            SelectStage(demo.SelectedStageId);
            initialized = true;
        }

        void EnsureInitialized()
        {
            if (!initialized) throw new InvalidOperationException("Initialize the selection screen before opening it");
        }

        void BeginPortraits()
        {
            if (portraits == null) portraits = gameObject.AddComponent<SelectionPortraits>();
            portraits.Begin(catalog);
        }

        public void ShowCharacters()
        {
            EnsureInitialized(); BeginPortraits();
            IsOpen = true; page = 0; activePlayer = 0;
            confirmed[0] = confirmed[1] = false;
            openedAt = Time.unscaledTime;
        }

        public void ShowStages()
        {
            EnsureInitialized(); BeginPortraits();
            IsOpen = true; page = 1;
            confirmed[0] = confirmed[1] = true;
            openedAt = stageChangedAt = Time.unscaledTime;
        }

        public void Hide() { IsOpen = false; }

        public void FocusPlayer(int player) { ValidatePlayer(player); activePlayer = player; }

        public void SelectCharacter(int player, string id)
        {
            EnsureInitialized(); ValidatePlayer(player);
            picks[player] = IndexOfCharacter(id); activePlayer = player;
            confirmed[player] = false; selectionTime[player] = Time.unscaledTime;
        }

        public void SelectStage(string id)
        {
            StageCatalog.Get(id);
            for (int i = 0; i < StageCatalog.All.Count; i++) if (StageCatalog.All[i].id == id) stageIndex = i;
            stageChangedAt = Time.unscaledTime;
        }

        public void ConfirmSelection()
        {
            EnsureInitialized();
            if (!IsOpen) return;
            if (page == 1)
            {
                demo.StartMatch(SelectedCharacterId(0), SelectedCharacterId(1), SelectedStageId);
                return;
            }
            confirmed[activePlayer] = true;
            selectionTime[activePlayer] = Time.unscaledTime;
            if (confirmed[0] && confirmed[1]) ShowStages();
            else activePlayer = 1 - activePlayer;
        }

        public void Back()
        {
            if (!IsOpen) return;
            if (page == 1) { ShowCharacters(); return; }
            if (confirmed[0] || confirmed[1])
            {
                confirmed[0] = confirmed[1] = false;
                return;
            }
            if (demo.CanResumeMatch) demo.ResumeFromSelection();
        }

        int IndexOfCharacter(string id)
        {
            catalog.Get(id);
            for (int i = 0; i < catalog.Characters.Count; i++) if (catalog.Characters[i].id == id) return i;
            throw new ArgumentException("Unknown character ID: " + id, nameof(id));
        }

        static void ValidatePlayer(int player)
        {
            if (player < 0 || player > 1) throw new ArgumentOutOfRangeException(nameof(player));
        }

        void Update()
        {
            if (!IsOpen) return;
            if (Input.GetKeyDown(KeyCode.Escape) || Input.GetKeyDown(KeyCode.Backspace)) { Back(); return; }
            if (page == 1)
            {
                if (Input.GetKeyDown(KeyCode.LeftArrow) || Input.GetKeyDown(KeyCode.A)) StepStage(-1);
                if (Input.GetKeyDown(KeyCode.RightArrow) || Input.GetKeyDown(KeyCode.D)) StepStage(1);
                if (Input.GetKeyDown(KeyCode.Return) || Input.GetKeyDown(KeyCode.KeypadEnter) || Input.GetKeyDown(KeyCode.Space)) ConfirmSelection();
                return;
            }
            if (Input.GetKeyDown(KeyCode.Tab)) activePlayer = 1 - activePlayer;
            if (Input.GetKeyDown(KeyCode.A)) Move(0, -1);
            if (Input.GetKeyDown(KeyCode.D)) Move(0, 1);
            if (Input.GetKeyDown(KeyCode.W) || Input.GetKeyDown(KeyCode.S)) Move(0, 2);
            if (Input.GetKeyDown(KeyCode.LeftArrow)) Move(1, -1);
            if (Input.GetKeyDown(KeyCode.RightArrow)) Move(1, 1);
            if (Input.GetKeyDown(KeyCode.UpArrow) || Input.GetKeyDown(KeyCode.DownArrow)) Move(1, 2);
            if (Input.GetKeyDown(KeyCode.F)) { activePlayer = 0; ConfirmSelection(); }
            else if (Input.GetKeyDown(KeyCode.KeypadEnter)) { activePlayer = 1; ConfirmSelection(); }
            else if (Input.GetKeyDown(KeyCode.Return) || Input.GetKeyDown(KeyCode.Space)) ConfirmSelection();
        }

        void Move(int player, int step)
        {
            int next = step == 2 ? (picks[player] + 2) % catalog.Characters.Count : picks[player] ^ 1;
            next %= catalog.Characters.Count;
            SelectCharacter(player, catalog.Characters[next].id);
        }

        void StepStage(int step)
        {
            int next = (stageIndex + step + StageCatalog.All.Count) % StageCatalog.All.Count;
            SelectStage(StageCatalog.All[next].id);
        }

        void EnsureArt()
        {
            if (style != null) return;
            fallback = Font.CreateDynamicFontFromOSFont(new[] { "Microsoft YaHei", "Arial" }, 28);
            display = Resources.Load<Font>("DollFight/Fonts/BarlowCondensed-ExtraBoldItalic") ?? fallback;
            technical = Resources.Load<Font>("DollFight/Fonts/Rajdhani-SemiBold") ?? fallback;
            style = new GUIStyle { richText = false, wordWrap = false, padding = new RectOffset(), margin = new RectOffset() };
            backdrop = new Texture2D(512, 288, TextureFormat.RGB24, false) { name = "Original violet street-print grain", filterMode = FilterMode.Bilinear, wrapMode = TextureWrapMode.Repeat };
            var pixels = new Color[512 * 288];
            var random = new System.Random(2729);
            for (int y = 0; y < 288; y++) for (int x = 0; x < 512; x++)
            {
                float grain = (float)random.NextDouble();
                float cloud = Mathf.PerlinNoise(x * .017f, y * .021f);
                float stroke = Mathf.Pow(Mathf.PerlinNoise(x * .008f + y * .06f, y * .14f), 6);
                float light = Mathf.Clamp01(1 - Vector2.Distance(new Vector2(x / 512f, y / 288f), new Vector2(.51f, .55f)) * 1.1f);
                pixels[y * 512 + x] = new Color(.035f + cloud * .045f + grain * .013f + stroke * .05f,
                    .016f + cloud * .021f + grain * .009f, .07f + light * .06f + cloud * .065f + grain * .018f);
            }
            backdrop.SetPixels(pixels); backdrop.Apply(false, true);
            fade = new Texture2D(1, 128, TextureFormat.RGBA32, false) { name = "Selection dark ink falloff", wrapMode = TextureWrapMode.Clamp };
            var gradient = new Color[128];
            for (int y = 0; y < 128; y++) gradient[y] = new Color(Ink.r, Ink.g, Ink.b, Mathf.Pow(1 - y / 127f, 2) * .98f);
            fade.SetPixels(gradient); fade.Apply(false, true);
        }

        void OnGUI()
        {
            if (!IsOpen || !initialized) return;
            EnsureArt();
            int oldDepth = GUI.depth; GUI.depth = -500;
            var oldMatrix = GUI.matrix; var oldColor = GUI.color;
            GUI.color = Color.white;
            GUI.DrawTexture(new Rect(0, 0, Screen.width, Screen.height), backdrop, ScaleMode.StretchToFill);
            float scale = Mathf.Min(Screen.width / CanvasWidth, Screen.height / CanvasHeight);
            GUI.matrix = Matrix4x4.TRS(new Vector3((Screen.width - CanvasWidth * scale) * .5f, (Screen.height - CanvasHeight * scale) * .5f, 0), Quaternion.identity, new Vector3(scale, scale, 1));
            float entrance = 1 - Mathf.Pow(1 - Mathf.Clamp01((Time.unscaledTime - openedAt) / .38f), 3);
            DrawBackdrop();
            var local = GUI.matrix;
            GUI.matrix = local * Matrix4x4.Translate(new Vector3(0, (1 - entrance) * 24, 0));
            if (page == 0) DrawCharacters(); else DrawStages();
            GUI.matrix = local;
            DrawChrome();
            GUI.matrix = oldMatrix; GUI.color = oldColor; GUI.depth = oldDepth;
        }

        void DrawBackdrop()
        {
            Text(new Rect(-30, 280, 2050, 450), "FIGHT", 470, new Color(.32f, .17f, .44f, .13f), display, TextAnchor.MiddleCenter);
            Slash(new Rect(-110, 360, 860, 190), -19, new Color(.37f, .045f, .34f, .5f));
            Slash(new Rect(1210, 365, 860, 190), -19, new Color(.09f, .19f, .37f, .55f));
            Slash(new Rect(-100, 750, 860, 14), -19, Pink * new Color(1, 1, 1, .38f));
            Slash(new Rect(1180, 775, 900, 14), -19, Cyan * new Color(1, 1, 1, .35f));
            // Registration ticks and broken dry-ink flecks give the poster a printed surface.
            for (int i = 0; i < 52; i++)
            {
                float x = (i * 331 + 43) % 1920, y = (i * 173 + 19) % 1080;
                Slash(new Rect(x, y, 3 + i % 7 * 4, 1 + i % 3), -19, new Color(.7f, .57f, .8f, .10f));
            }
            Line(new Vector2(60, 88), new Vector2(1860, 88), new Color(.56f, .42f, .64f, .4f), 1);
        }

        void DrawChrome()
        {
            Text(new Rect(62, 24, 490, 50), "DOLL / FIGHT", 40, Paper, display);
            Text(new Rect(1070, 32, 790, 35), "LOCAL VERSUS    /    2 PLAYERS    /    OFFLINE", 23, Muted, technical, TextAnchor.MiddleRight);
            Text(new Rect(69, 112, 1640, 140), page == 0 ? "CHARACTER SELECT" : "STAGE SELECT", 117, Paper, display);
            Text(new Rect(1677, 134, 182, 63), page == 0 ? "01 / 02" : "02 / 02", 39, Muted, technical, TextAnchor.MiddleRight);
            Box(new Rect(60, 1014, 1800, 1), new Color(.56f, .42f, .64f, .4f));
            if (page == 0)
            {
                Text(new Rect(62, 1030, 1350, 32), "P1  WASD / F 确认     P2  方向键     Tab  切换玩家     Enter  确认     Esc  返回", 21, Paper, fallback);
                Text(new Rect(1510, 1030, 350, 32), "CHOOSE YOUR FIGHTER", 22, Muted, technical, TextAnchor.MiddleRight);
            }
            else
            {
                Text(new Rect(62, 1030, 1350, 32), "A / D  或  ← / →  切换场地     Enter  开始对战     Esc  返回角色", 21, Paper, fallback);
                Text(new Rect(1510, 1030, 350, 32), "MAKE THE STAGE YOURS", 22, Muted, technical, TextAnchor.MiddleRight);
            }
        }

        void DrawCharacters()
        {
            DrawFighter(0); DrawFighter(1);
            Text(new Rect(794, 305, 332, 42), "THE ROSTER", 31, Paper, technical, TextAnchor.MiddleCenter);
            for (int i = 0; i < catalog.Characters.Count; i++)
            {
                var rect = new Rect(800 + i % 2 * 168, 360 + i / 2 * 204, 152, 186);
                DrawRosterCard(rect, i);
            }
            Text(new Rect(788, 790, 344, 30), "选择正在编辑的玩家", 20, Muted, fallback, TextAnchor.MiddleCenter);
            for (int p = 0; p < 2; p++)
            {
                var rect = new Rect(800 + p * 168, 830, 152, 52);
                var color = p == 0 ? Pink : Cyan;
                Box(rect, activePlayer == p ? color : new Color(.15f, .10f, .23f));
                Frame(rect, color, activePlayer == p ? 3 : 1);
                Text(rect, "P" + (p + 1) + (confirmed[p] ? "  READY" : "  EDIT"), 25, activePlayer == p ? Ink : color, technical, TextAnchor.MiddleCenter);
                if (Hit(rect)) FocusPlayer(p);
            }
            string next = "确认 P" + (activePlayer + 1) + "   →";
            var buttonRect = new Rect(800, 906, 320, 68);
            DrawButton(buttonRect, next, activePlayer == 0 ? Pink : Cyan, true);
            if (Hit(buttonRect)) ConfirmSelection();
        }

        void DrawFighter(int player)
        {
            var character = catalog.Characters[picks[player]];
            var color = player == 0 ? Pink : Cyan;
            bool left = player == 0;
            float change = Mathf.Clamp01((Time.unscaledTime - selectionTime[player]) / .24f);
            float offset = (1 - change) * 24 * (left ? -1 : 1);
            var portraitRect = new Rect((left ? -2 : 1172) + offset, 237, 750, 820);
            var texture = portraits != null ? portraits.Get(character.id, player) : null;
            if (texture != null)
            {
                // A crisp offset print shadow separates pale costumes and hats from the violet wall.
                // The lower thigh may fall behind the name ink, while the full head/hat stays visible.
                GUI.BeginGroup(new Rect(0, 0, CanvasWidth, 1010));
                var shadowRect = portraitRect; shadowRect.x += left ? -8 : 8; shadowRect.y += 5;
                GUI.color = new Color(color.r, color.g, color.b, .28f); GUI.DrawTexture(shadowRect, texture, ScaleMode.ScaleToFit, true);
                GUI.color = Color.white; GUI.DrawTexture(portraitRect, texture, ScaleMode.ScaleToFit, true);
                GUI.EndGroup();
            }
            else
            {
                Text(new Rect(left ? 130 : 1290, 440, 500, 180), "D / F", 150, new Color(.5f, .37f, .66f, .4f), display, TextAnchor.MiddleCenter);
                string loading = !string.IsNullOrEmpty(PortraitError) ? "角色展示暂不可用" : "角色准备中  " + (portraits != null ? portraits.LoadedCount : 0) + " / " + catalog.Characters.Count;
                Text(new Rect(left ? 130 : 1290, 630, 500, 40), loading, 23, Muted, fallback, TextAnchor.MiddleCenter);
            }
            var slot = new Rect(left ? 70 : 1390, left ? 297 : 226, 460, 53);
            Box(new Rect(slot.x, slot.y, 6, slot.height), color);
            Text(new Rect(slot.x + 20, slot.y - 5, left ? 90 : 290, 55), left ? "P1" : "P2 / PLAYER TWO", left ? 31 : 28, color, technical);
            if (activePlayer == player && !confirmed[player])
                Text(new Rect(slot.x + (left ? 20 : 326), slot.y + (left ? 44 : 9), left ? 350 : 132, 32), "正在选择", left ? 22 : 20, Paper, fallback);
            if (confirmed[player])
            {
                float badgeX = slot.x + (left ? 20 : 326), badgeY = slot.y + (left ? 50 : 9);
                Box(new Rect(badgeX, badgeY, 130, 34), color);
                Text(new Rect(badgeX, badgeY - 2, 130, 36), "READY", 26, Ink, technical, TextAnchor.MiddleCenter);
            }
            if (Hit(new Rect(slot.x, slot.y, slot.width, 92))) FocusPlayer(player);
            // Names sit on an ink gradient rather than competing with the model's face.
            GUI.color = Color.white;
            GUI.DrawTexture(new Rect(left ? 0 : 1170, 745, 750, 265), fade, ScaleMode.StretchToFill, true);
            float nameX = left ? 66 : 1185;
            var align = left ? TextAnchor.MiddleLeft : TextAnchor.MiddleRight;
            float fontSize = character.displayName.Length > 9 ? 84 : 111;
            Text(new Rect(nameX, 821, 665, 125), character.displayName, (int)fontSize, Paper, display, align);
            Text(new Rect(nameX + (left ? 4 : 0), 945, 660, 34), "0" + (picks[player] + 1) + "    /    " + Archetype(character.id), 24, color, technical, align);
            Box(new Rect(left ? 71 : 1495, 991, 350, 4), color);
        }

        static string Archetype(string id)
        {
            switch (id)
            {
                case "tripo-b9e9ce29": return "WILD CARD";
                case "team": return "THE CHALLENGER";
                case "nozomi": return "NOZOMI";
                case "mizore": return "MIZORE";
                default: return "FIGHTER";
            }
        }

        void DrawRosterCard(Rect rect, int index)
        {
            bool p1 = picks[0] == index, p2 = picks[1] == index;
            var character = catalog.Characters[index];
            bool hovered = rect.Contains(PointerPosition());
            Box(rect, hovered ? new Color(.24f, .14f, .34f) : new Color(.12f, .075f, .20f));
            var texture = portraits != null ? portraits.GetRoster(character.id) : null;
            var imageRect = new Rect(rect.x + 3, rect.y + 3, rect.width - 6, rect.height - 32);
            if (texture != null)
            {
                GUI.DrawTexture(imageRect, texture, ScaleMode.ScaleAndCrop, true);
            }
            else Text(imageRect, "0" + (index + 1), 76, new Color(.4f, .31f, .51f), display, TextAnchor.MiddleCenter);
            Box(new Rect(rect.x, rect.yMax - 32, rect.width, 32), new Color(.045f, .02f, .08f, .95f));
            Text(new Rect(rect.x + 6, rect.yMax - 33, rect.width - 12, 32), character.displayName, character.displayName.Length > 9 ? 18 : 22, Paper, technical, TextAnchor.MiddleCenter);
            Frame(rect, p1 ? Pink : p2 ? Cyan : new Color(.37f, .27f, .46f), p1 || p2 ? 4 : 1);
            if (p1 && p2) Frame(new Rect(rect.x + 6, rect.y + 6, rect.width - 12, rect.height - 12), Cyan, 3);
            if (p1) Tag(new Rect(rect.x - 3, rect.y - 10, 48, 30), "P1", Pink);
            if (p2) Tag(new Rect(rect.xMax - 45, rect.y - 10, 48, 30), "P2", Cyan);
            if (hovered && !p1 && !p2) Frame(new Rect(rect.x - 3, rect.y - 3, rect.width + 6, rect.height + 6), Paper, 2);
            if (Hit(rect)) SelectCharacter(activePlayer, character.id);
        }

        void DrawStages()
        {
            var stage = StageCatalog.All[stageIndex];
            Text(new Rect(70, 246, 650, 40), "选择场地  /  下一场，在这里开战", 24, Muted, fallback);
            var hero = new Rect(70, 310, 1242, 486);
            Texture image = StageImage(stage);
            float reveal = Mathf.Clamp01((Time.unscaledTime - stageChangedAt) / .26f);
            Box(hero, new Color(.11f, .07f, .18f));
            if (image != null)
            {
                GUI.color = new Color(1, 1, 1, .65f + reveal * .35f);
                GUI.DrawTexture(hero, image, ScaleMode.ScaleAndCrop, true); GUI.color = Color.white;
            }
            else
            {
                Text(hero, stage.displayName, 104, new Color(.6f, .49f, .71f), display, TextAnchor.MiddleCenter);
                Text(new Rect(hero.x, hero.center.y + 80, hero.width, 35), "场地预览准备中", 23, Muted, fallback, TextAnchor.MiddleCenter);
            }
            GUI.DrawTexture(new Rect(hero.x, hero.y + hero.height * .38f, hero.width, hero.height * .62f), fade, ScaleMode.StretchToFill, true);
            Frame(hero, new Color(.5f, .39f, .63f), 1);
            Tag(new Rect(hero.x + 24, hero.y + 24, 198, 34), "LOCATION  /  0" + (stageIndex + 1), Acid);
            Text(new Rect(hero.x + 28, hero.yMax - 99, hero.width - 56, 76), stage.displayName, 66, Paper, display);
            Box(new Rect(hero.x, hero.yMax - 4, hero.width, 4), Acid);
            Text(new Rect(1372, 290, 455, 168), "0" + (stageIndex + 1), 158, new Color(.49f, .29f, .68f), display);
            string stageName = stage.displayName.Replace("-", "-\n");
            if (stage.id == "cloud") stageName = "CLOUD\nSANCTUM";
            if (stage.id == "underground") stageName = "UNDER-\nGROUND";
            Text(new Rect(1380, 465, 470, 180), stageName, 76, Paper, display, TextAnchor.UpperLeft);
            Text(new Rect(1386, 649, 455, 38), stage.subtitle, 25, Muted, fallback);
            var fight = new Rect(1380, 718, 470, 78);
            DrawButton(fight, "FIGHT   →", Acid, false);
            if (Hit(fight)) ConfirmSelection();
            for (int i = 0; i < StageCatalog.All.Count; i++)
                DrawStageCard(new Rect(70 + i * 420, 838, 400, 155), i);
            for (int p = 0; p < 2; p++)
            {
                Color color = p == 0 ? Pink : Cyan;
                float y = 850 + p * 78;
                Text(new Rect(1385, y, 65, 52), "P" + (p + 1), 36, color, technical);
                Text(new Rect(1463, y, 385, 52), catalog.Characters[picks[p]].displayName, 34, Paper, display);
                Box(new Rect(1386, y + 57, 464, 1), new Color(.56f, .42f, .64f, .4f));
            }
        }

        void DrawStageCard(Rect rect, int index)
        {
            bool selected = stageIndex == index;
            var stage = StageCatalog.All[index];
            var image = StageImage(stage);
            Box(rect, new Color(.12f, .075f, .20f));
            if (image != null)
            {
                GUI.color = selected ? Color.white : new Color(.72f, .68f, .77f);
                GUI.DrawTexture(rect, image, ScaleMode.ScaleAndCrop, true); GUI.color = Color.white;
            }
            GUI.DrawTexture(rect, fade, ScaleMode.StretchToFill, true);
            Frame(rect, selected ? Acid : new Color(.43f, .32f, .53f), selected ? 4 : 1);
            Text(new Rect(rect.x + 15, rect.y + 6, 75, 49), "0" + (index + 1), 39, selected ? Acid : Paper, display);
            Text(new Rect(rect.x + 17, rect.yMax - 58, rect.width - 34, 48), stage.displayName, 32, Paper, display);
            if (selected) Tag(new Rect(rect.xMax - 113, rect.y + 13, 98, 28), "SELECTED", Acid);
            if (rect.Contains(PointerPosition()) && !selected) Frame(rect, Paper, 2);
            if (Hit(rect)) SelectStage(stage.id);
        }

        Texture StageImage(StageDefinition stage)
        {
            if (!stageImages.TryGetValue(stage.id, out var image) || image == null)
            {
                image = Resources.Load<Texture2D>(stage.previewResource);
                if (image != null) stageImages[stage.id] = image;
            }
            return image;
        }

        void DrawButton(Rect rect, string text, Color color, bool chinese)
        {
            bool hover = rect.Contains(PointerPosition());
            Slash(new Rect(rect.x + 8, rect.y + 6, rect.width, rect.height), 0, new Color(0, 0, 0, .4f));
            Box(rect, hover ? Color.Lerp(color, Color.white, .22f) : color);
            Box(new Rect(rect.x + 7, rect.y + 7, 3, rect.height - 14), Ink);
            Text(new Rect(rect.x + 22, rect.y, rect.width - 42, rect.height), text, chinese ? 29 : 46, Ink, chinese ? fallback : display, TextAnchor.MiddleCenter);
        }

        void Tag(Rect rect, string text, Color color)
        {
            Box(rect, color); Text(rect, text, 22, Ink, technical, TextAnchor.MiddleCenter);
        }

        void Text(Rect rect, string text, int size, Color color, Font font, TextAnchor alignment = TextAnchor.MiddleLeft)
        {
            style.font = font; style.fontSize = size; style.fontStyle = FontStyle.Normal; style.alignment = alignment;
            style.normal.textColor = color; GUI.Label(rect, text, style);
        }

        static void Box(Rect rect, Color color)
        {
            GUI.color = color; GUI.DrawTexture(rect, Texture2D.whiteTexture); GUI.color = Color.white;
        }

        static void Frame(Rect rect, Color color, float width)
        {
            Box(new Rect(rect.x, rect.y, rect.width, width), color); Box(new Rect(rect.x, rect.yMax - width, rect.width, width), color);
            Box(new Rect(rect.x, rect.y, width, rect.height), color); Box(new Rect(rect.xMax - width, rect.y, width, rect.height), color);
        }

        static void Slash(Rect rect, float angle, Color color)
        {
            var matrix = GUI.matrix; GUIUtility.RotateAroundPivot(angle, rect.center); Box(rect, color); GUI.matrix = matrix;
        }

        static void Line(Vector2 from, Vector2 to, Color color, float width)
        {
            var matrix = GUI.matrix; float angle = Mathf.Atan2(to.y - from.y, to.x - from.x) * Mathf.Rad2Deg;
            GUIUtility.RotateAroundPivot(angle, from); Box(new Rect(from.x, from.y, (to - from).magnitude, width), color); GUI.matrix = matrix;
        }

        static bool Hit(Rect rect)
        {
            var current = Event.current;
            if (current.type != EventType.MouseDown || current.button != 0 || !rect.Contains(PointerPosition())) return false;
            current.Use(); return true;
        }

        static Vector2 PointerPosition()
        {
            var pointer = Input.mousePosition;
            return GUI.matrix.inverse.MultiplyPoint3x4(new Vector3(pointer.x, Screen.height - pointer.y, 0));
        }

        void OnDestroy()
        {
            if (portraits != null) Destroy(portraits);
            if (fallback != null) Destroy(fallback);
            if (backdrop != null) Destroy(backdrop);
            if (fade != null) Destroy(fade);
        }
    }
}
