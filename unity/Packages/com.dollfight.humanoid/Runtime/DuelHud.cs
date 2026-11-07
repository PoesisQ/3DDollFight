using UnityEngine;

namespace DollFight
{
    /// <summary>Stable identity-to-screen mapping shared by HUD rails and player-view cameras.</summary>
    public sealed class DuelHudSides
    {
        Camera source;
        Vector3 viewRight;
        bool resolved;
        int leftPlayer;

        public int PlayerAtSide(int side) => side == 0 ? leftPlayer : 1 - leftPlayer;
        public int SideOfPlayer(int player) => player == leftPlayer ? 0 : 1;

        public void Refresh(Camera camera, Vector3 playerOne, Vector3 playerTwo)
        {
            if (camera == null) return;
            // Crossed limbs, motion, seeking and short camera shake keep one stable
            // arrangement. A replacement/reversed main camera establishes a new one.
            if (resolved && source == camera && Vector3.Dot(viewRight, camera.transform.right) > .5f) return;
            Vector3 one = camera.WorldToViewportPoint(playerOne), two = camera.WorldToViewportPoint(playerTwo);
            if (one.z <= 0 || two.z <= 0 || Mathf.Abs(one.x - two.x) < .001f) return;
            leftPlayer = one.x < two.x ? 0 : 1;
            source = camera; viewRight = camera.transform.right; resolved = true;
        }
    }

    /// <summary>Native arcade presentation. All meters and results are exported duel values.</summary>
    public sealed class DuelHud
    {
        static readonly Color Ink = new Color(.025f, .031f, .045f);
        static readonly Color White = new Color(.98f, .96f, .88f);
        static readonly Color Muted = new Color(.65f, .71f, .75f);
        static readonly Color Pink = new Color(.953f, .220f, .616f);
        static readonly Color Cyan = new Color(.251f, .812f, 1f);
        static readonly Color Acid = new Color(.91f, 1f, .26f);
        readonly float[] trail = { 100, 100 }, previous = { 100, 100 }, hold = { 0, 0 };
        readonly DuelHudSides sides = new DuelHudSides();
        Font fallback, displayFont, numberFont;
        GUIStyle label, button, slider, thumb;
        bool debugOpen, wasFinished;
        float settingsFade, finishAge;
        public bool SettingsOpen { get; set; }
        public bool DebugOpen { get => debugOpen; set => debugOpen = value; }

        public int DisplaySide(DollFightDemo demo, int player)
        {
            if (demo != null && demo.Actors != null && demo.Actors.Length >= 2 &&
                demo.Actors[0] != null && demo.Actors[1] != null)
            {
                var one = demo.Actors[0].Bones;
                var two = demo.Actors[1].Bones;
                if (one != null && two != null && one.Length > 0 && two.Length > 0 && one[0] != null && two[0] != null)
                    sides.Refresh(demo.MainCamera, one[0].position, two[0].position);
            }
            return sides.SideOfPlayer(player);
        }

        public void Reset(DuelFrame frame)
        {
            for (int i = 0; i < 2; i++) { trail[i] = previous[i] = Value(frame?.health, i); hold[i] = 0; }
            wasFinished = false; finishAge = 0;
        }

        public void Tick(DuelFrame frame)
        {
            for (int i = 0; i < 2; i++)
            {
                float health = Value(frame?.health, i);
                if (health < previous[i]) hold[i] = .48f;
                if (health > previous[i]) trail[i] = health;
                hold[i] -= Time.unscaledDeltaTime;
                if (hold[i] <= 0) trail[i] = Mathf.MoveTowards(trail[i], health, 40 * Time.unscaledDeltaTime);
                previous[i] = health;
            }
            bool finished = frame?.matchState == "finished";
            finishAge = finished && wasFinished ? finishAge + Time.unscaledDeltaTime : 0;
            wasFinished = finished;
            settingsFade = Mathf.MoveTowards(settingsFade, SettingsOpen ? 1 : 0, Time.unscaledDeltaTime * 9);
        }

        public void Dispose()
        {
            // Resources fonts are shared. Only the OS fallback belongs to this HUD.
            if (fallback != null) Object.Destroy(fallback);
            fallback = null; displayFont = null; numberFont = null; label = null;
        }

        static float Value(float[] values, int index) => values != null && values.Length > index ? values[index] : 100;
        static Color PlayerColor(int player) => player == 0 ? Pink : Cyan;
        static Color Alpha(Color color, float alpha) { color.a = alpha; return color; }

        void EnsureStyles()
        {
            if (label != null) return;
            fallback = Font.CreateDynamicFontFromOSFont(new[] { "Microsoft YaHei", "Arial" }, 24);
            displayFont = Resources.Load<Font>("DollFight/Fonts/BarlowCondensed-ExtraBoldItalic");
            numberFont = Resources.Load<Font>("DollFight/Fonts/Rajdhani-SemiBold");
            label = new GUIStyle(GUI.skin.label) { font = fallback, padding = new RectOffset(), clipping = TextClipping.Clip, richText = false };
            button = new GUIStyle(GUI.skin.button) { font = fallback, fontSize = 15, alignment = TextAnchor.MiddleCenter,
                border = new RectOffset(), padding = new RectOffset() };
            foreach (var state in new[] { button.normal, button.hover, button.active, button.focused })
            { state.background = null; state.textColor = White; }
            slider = new GUIStyle(GUIStyle.none) { fixedHeight = 24, margin = new RectOffset(), padding = new RectOffset() };
            thumb = new GUIStyle(GUI.skin.horizontalSliderThumb) { fixedWidth = 12, fixedHeight = 21 };
        }

        static void Fill(Rect rect, Color color)
        {
            Color old = GUI.color;
            GUI.color = old * color;
            GUI.DrawTexture(rect, Texture2D.whiteTexture);
            GUI.color = old;
        }

        // A shear keeps the cut a fixed pixel size at every bar width, without runtime textures.
        static void Slash(Rect rect, Color color, float cut = 10)
        {
            Matrix4x4 old = GUI.matrix, shear = Matrix4x4.identity;
            shear.m01 = -cut / Mathf.Max(1, rect.height);
            shear.m03 = cut * .5f;
            GUI.matrix = old * Matrix4x4.Translate(new Vector3(rect.x, rect.y, 0)) * shear;
            Fill(new Rect(0, 0, rect.width, rect.height), color);
            GUI.matrix = old;
        }

        void Text(Rect rect, string text, int size = 16, Color? color = null, TextAnchor align = TextAnchor.MiddleLeft, bool bold = false)
        {
            Write(rect, text, size, color ?? White, align, fallback, bold ? FontStyle.Bold : FontStyle.Normal);
        }

        void Display(Rect rect, string text, int size, Color? color = null, TextAnchor align = TextAnchor.MiddleLeft)
        {
            Write(rect, text, size, color ?? White, align, displayFont != null ? displayFont : fallback, FontStyle.Normal);
        }

        void Number(Rect rect, string text, int size, Color? color = null, TextAnchor align = TextAnchor.MiddleCenter)
        {
            Write(rect, text, size, color ?? White, align, numberFont != null ? numberFont : fallback, FontStyle.Normal);
        }

        void Write(Rect rect, string text, int size, Color color, TextAnchor align, Font font, FontStyle style)
        {
            label.font = font; label.fontSize = size; label.fontStyle = style;
            label.alignment = align; label.normal.textColor = color;
            GUI.Label(rect, text ?? "", label);
        }

        bool Button(Rect rect, string text, bool selected = false, bool primary = false)
        {
            string id = "DollFight." + text;
            bool hover = GUI.enabled && rect.Contains(Event.current.mousePosition);
            bool focus = GUI.GetNameOfFocusedControl() == id;
            Color accent = primary ? Acid : Cyan;
            Fill(rect, primary ? (hover ? White : Acid) : hover || focus ? new Color(.16f, .23f, .28f) : new Color(.075f, .10f, .13f));
            Fill(new Rect(rect.x, rect.yMax - (hover || focus ? 3 : 1), rect.width, hover || focus ? 3 : 1), selected || hover || focus || primary ? accent : new Color(.25f, .30f, .34f));
            if (selected) Fill(new Rect(rect.x, rect.y, 3, rect.height), accent);
            foreach (var state in new[] { button.normal, button.hover, button.active, button.focused }) state.textColor = primary ? Ink : White;
            GUI.SetNextControlName(id);
            return GUI.Button(rect, text, button);
        }

        float Slider(Rect rect, float value, float maximum)
        {
            float fraction = maximum > 0 ? Mathf.Clamp01(value / maximum) : 0;
            Fill(new Rect(rect.x, rect.y + 9, rect.width, 4), new Color(.25f, .31f, .35f));
            Fill(new Rect(rect.x, rect.y + 9, rect.width * fraction, 4), Cyan);
            return GUI.HorizontalSlider(rect, value, 0, maximum, slider, thumb);
        }

        static string Clock(float seconds, bool countdown = true)
        {
            int whole = Mathf.Max(0, countdown ? Mathf.CeilToInt(seconds) : Mathf.FloorToInt(seconds));
            return $"{whole / 60:00}:{whole % 60:00}";
        }

        public void Draw(DollFightDemo demo, Rect arena)
        {
            EnsureStyles();
            Fill(new Rect(0, 0, Screen.width, arena.y), Ink);
            Fill(new Rect(0, arena.y, arena.x, arena.height), Ink);
            Fill(new Rect(arena.xMax, arena.y, Screen.width - arena.xMax, arena.height), Ink);
            Fill(new Rect(0, arena.yMax, Screen.width, Screen.height - arena.yMax), Ink);
            Matrix4x4 old = GUI.matrix;
            bool enabled = GUI.enabled;
            float scale = arena.width / 1440f;
            GUI.matrix = Matrix4x4.TRS(new Vector3(arena.x, arena.y, 0), Quaternion.identity, new Vector3(scale, scale, 1));
            GUI.enabled = enabled && !SettingsOpen;
            if (demo.Ready) ArenaHud(demo); else Loading(demo);
            if (demo.showPlayerViews && demo.Ready)
            {
                for (int i = 0; i < 2; i++)
                {
                    Rect inset = DuelPresentationLayout.PlayerView(new Rect(0, 0, 1440, 810), DisplaySide(demo, i));
                    Fill(new Rect(inset.x, inset.y, inset.width, 25), Alpha(Ink, .92f));
                    Text(new Rect(inset.x + 10, inset.y, inset.width - 20, 25), $"P{i + 1}   /   PLAYER VIEW", 12, PlayerColor(i));
                    Fill(new Rect(inset.x, inset.y + 25, 2, inset.height - 25), PlayerColor(i));
                }
            }
            GUI.matrix = old;
            Toolbar(demo);
            GUI.enabled = enabled;
            if (settingsFade > 0) Settings(demo);
        }

        void ArenaHud(DollFightDemo demo)
        {
            var f = demo.CurrentFrame;
            // Separated fighter rails leave the arena and central sightline visible.
            Fill(new Rect(0, 0, 1440, 32), Alpha(Ink, .58f));
            Display(new Rect(34, 5, 182, 31), "DOLL FIGHT", 27);
            Text(new Rect(224, 10, 450, 23), "MOTION CAPTURE REHEARSAL", 10, White);
            string venue = StageCatalog.Get(demo.SelectedStageId).displayName;
            Text(new Rect(950, 10, 456, 23), venue + "   /   " + (demo.KnockoutMode ? "KNOCKOUT DUEL" : "THREE ROUND DUEL"), 10, White, TextAnchor.MiddleRight);
            var art = demo.GetComponent<DuelArtDirection>();
            DisplaySide(demo, 0);
            for (int side = 0; side < 2; side++)
            {
                int player = sides.PlayerAtSide(side);
                string name = demo.SelectedCharacter(player).displayName;
                Fighter(f, player, side == 1, name, art != null ? art.Portrait(player) : null, !demo.KnockoutMode);
            }
            Slash(new Rect(649, 37, 142, 74), Alpha(Ink, .92f), 17);
            Fill(new Rect(660, 36, 120, 2), Acid);
            Text(new Rect(631, 14, 178, 22), demo.KnockoutMode ? "KNOCKOUT" : $"ROUND {f?.round ?? 1} / {demo.RoundCount}", 11, White, TextAnchor.MiddleCenter, true);
            float remaining = demo.KnockoutMode ? Mathf.Max(0, demo.RegulationDuration - demo.time) : f?.roundRemaining ?? 30;
            float seconds = demo.DisplaySeconds(remaining);
            Number(new Rect(636, 35, 168, 74), demo.KnockoutMode ? Clock(seconds) : Mathf.CeilToInt(seconds).ToString("00"), 52, seconds <= 30 ? Acid : White);
            Slash(new Rect(652, 112, 136, 22), Alpha(Ink, .82f), 5);
            Text(new Rect(630, 113, 180, 21), f?.overtime == true ? "OVERTIME / 加时" : "HP ZERO TO WIN", 10, f?.overtime == true ? Acid : White, TextAnchor.MiddleCenter);
            Contact(demo);
            if (demo.MatchFinished) Result(demo);
            else if (demo.KnockoutMode && demo.time < 1.5f) Intro(demo.time, "READY", "FIGHT", "单局对决 · HP 归零决胜");
            else if (!demo.KnockoutMode && f != null)
            {
                if (f.roundState == "finished") RoundResult(f);
                else if (f.roundRemaining > 28.5f) Intro(30 - f.roundRemaining, $"ROUND {f.round}", "FIGHT", $"三回合对决 · 第 {f.round} 回合");
            }
            if (!demo.KnockoutMode && !demo.MatchFinished)
                Text(new Rect(390, demo.showPlayerViews ? 568 : 738, 660, 25), f?.intent, 14, White, TextAnchor.MiddleCenter);
            Slash(new Rect(28, 764, 208, 23), Alpha(Ink, .80f), 5);
            Slash(new Rect(1252, 764, 160, 23), Alpha(Ink, .80f), 5);
            Text(new Rect(34, 765, 600, 20), "动捕动作排练  /  非实时对战", 12, White);
            Text(new Rect(1010, 765, 396, 20), demo.playing ? "REPLAY IN MOTION" : demo.MatchFinished ? "MATCH COMPLETE" : "REPLAY PAUSED", 10, demo.playing ? White : Acid, TextAnchor.MiddleRight);
        }

        void Fighter(DuelFrame frame, int player, bool right, string name, Texture portrait, bool showWins)
        {
            Color accent = PlayerColor(player);
            float hp = Value(frame?.health, player), guard = Mathf.Clamp01(Value(frame?.guardEnergy, player) / 100);
            float x = right ? 824 : 116, px = right ? 1340 : 34;
            Slash(new Rect(right ? 818 : 110, 39, 514, 88), Alpha(Ink, .83f), right ? -16 : 16);
            Fill(new Rect(px - 2, 39, 68, 90), accent);
            Rect portraitArea = new Rect(px, 41, 64, 86);
            Fill(portraitArea, new Color(.10f, .13f, .17f));
            if (portrait != null) GUI.DrawTexture(portraitArea, portrait, ScaleMode.ScaleToFit, true);
            else Display(portraitArea, $"{player + 1}", 56, Alpha(accent, .65f), TextAnchor.MiddleCenter);
            Fill(new Rect(px, 107, 64, 20), Alpha(Ink, .9f));
            Number(new Rect(px, 104, 64, 24), $"P{player + 1}", 20, accent);
            Display(new Rect(x + (right ? 70 : 0), 34, 430, 43), name, 33, White, right ? TextAnchor.MiddleRight : TextAnchor.MiddleLeft);
            Number(new Rect(right ? x : x + 423, 42, 76, 30), hp.ToString("000"), 27, hp <= 25 ? Acid : accent, right ? TextAnchor.MiddleLeft : TextAnchor.MiddleRight);
            Rect bar = new Rect(x, 78, 500, 25);
            Slash(new Rect(bar.x - 3, bar.y - 3, bar.width + 6, bar.height + 6), new Color(.44f, .49f, .51f), right ? -12 : 12);
            Slash(bar, new Color(.075f, .085f, .11f), right ? -10 : 10);
            Meter(bar, Mathf.Clamp01(trail[player] / 100), Alpha(White, .84f), right);
            Color life = hp <= 25 ? Color.Lerp(accent, Acid, .25f + .12f * Mathf.Sin(Time.unscaledTime * 7)) : accent;
            Meter(bar, Mathf.Clamp01(hp / 100), life, right);
            // Six guard segments represent the existing guardEnergy, including partial segments.
            const float gap = 5, segment = (500 - gap * 5) / 6;
            for (int j = 0; j < 6; j++)
            {
                float sx = right ? x + 500 - segment - j * (segment + gap) : x + j * (segment + gap);
                var slot = new Rect(sx, 112, segment, 6);
                Slash(slot, new Color(.23f, .27f, .30f), 3);
                float charge = Mathf.Clamp01(guard * 6 - j);
                if (charge > 0) Slash(new Rect(right ? slot.xMax - segment * charge : sx, 112, segment * charge, 6), Alpha(accent, .85f), 3);
            }
            Slash(new Rect(right ? x - 4 : x + 436, 122, 68, 18), Alpha(Ink, .82f), 4);
            Text(new Rect(x, 122, 500, 18), hp <= 25 ? "CRITICAL" : "GUARD", 9, hp <= 25 ? Acid : White, right ? TextAnchor.MiddleLeft : TextAnchor.MiddleRight);
            int wins = frame?.wins != null && frame.wins.Length > player ? frame.wins[player] : 0;
            for (int j = 0; showWins && j < 3; j++) Slash(new Rect(right ? x + 486 - j * 22 : x + j * 22, 125, 14, 6), j < wins ? Acid : new Color(.22f, .27f, .29f), 3);
        }

        static void Meter(Rect rect, float value, Color color, bool right)
        {
            if (value <= 0) return;
            float width = rect.width * value;
            Slash(new Rect(right ? rect.xMax - width : rect.x, rect.y, width, rect.height), color, right ? -10 : 10);
            if (width > 16) Slash(new Rect(right ? rect.xMax - width + 3 : rect.x + 3, rect.y + 3, width - 6, 2), Alpha(White, .35f), 1);
        }

        void Contact(DollFightDemo demo)
        {
            var contact = demo.Feedback?.LastContact;
            if (contact == null || demo.Feedback.ContactAge >= 1.55f || demo.MatchFinished) return;
            float age = demo.Feedback.ContactAge, alpha = Mathf.Clamp01((1.55f - age) * 4);
            bool right = sides.SideOfPlayer(contact.attacker) == 1;
            float enter = 1 - Mathf.Pow(1 - Mathf.Clamp01(age / .18f), 3);
            float x = right ? 1112 + (1 - enter) * 30 : 36 - (1 - enter) * 30;
            Color accent = PlayerColor(contact.attacker);
            Color old = GUI.color; GUI.color = old * new Color(1, 1, 1, alpha);
            Fill(new Rect(right ? x + 288 : x, 189, 4, contact.comboCount > 1 ? 100 : 58), accent);
            Text(new Rect(x + 14, 185, 264, 32), contact.label, 19, White, right ? TextAnchor.MiddleRight : TextAnchor.MiddleLeft, true);
            Text(new Rect(x + 14, 220, 264, 22), contact.damage > 0 ? $"{contact.damage:0.#} DAMAGE" : "GUARD CONTACT", 11, accent, right ? TextAnchor.MiddleRight : TextAnchor.MiddleLeft);
            if (contact.comboCount > 1) Display(new Rect(x + 14, 247, 264, 47), $"{contact.comboCount} HIT COMBO", 34, accent, right ? TextAnchor.MiddleRight : TextAnchor.MiddleLeft);
            GUI.color = old;
        }

        void Intro(float time, string ready, string fight, string subtitle)
        {
            bool attack = time >= .7f;
            float local = attack ? time - .7f : time;
            float enter = Mathf.Clamp01(local / .16f), alpha = Mathf.Clamp01((1.5f - time) / .22f);
            float zoom = Mathf.Lerp(attack ? 1.26f : .88f, 1, 1 - Mathf.Pow(1 - enter, 3));
            Matrix4x4 matrix = GUI.matrix; Color color = GUI.color;
            GUI.color = color * new Color(1, 1, 1, alpha);
            GUI.matrix = matrix * Matrix4x4.Translate(new Vector3(720, 323, 0)) * Matrix4x4.Scale(new Vector3(zoom, zoom, 1)) * Matrix4x4.Translate(new Vector3(-720, -323, 0));
            Slash(new Rect(attack ? 470 : 442, 278, attack ? 500 : 556, 94), Alpha(Ink, .80f), 44);
            Slash(new Rect(452, 367, 533, 4), attack ? Acid : Pink, 3);
            Display(new Rect(287, 224, 880, 174), attack ? fight : ready, 142, attack ? Acid : White, TextAnchor.MiddleCenter);
            Text(new Rect(430, 401, 580, 28), subtitle, 17, White, TextAnchor.MiddleCenter);
            GUI.matrix = matrix; GUI.color = color;
        }

        void Result(DollFightDemo demo)
        {
            var frame = demo.CurrentFrame;
            Color accent = frame.matchWinner < 0 ? Acid : PlayerColor(frame.matchWinner);
            if (demo.KnockoutMode && finishAge < 1.15f)
            {
                float enter = Mathf.Clamp01(finishAge / .22f), outAlpha = Mathf.Clamp01((1.15f - finishAge) / .20f);
                float zoom = Mathf.Lerp(1.8f, 1, 1 - Mathf.Pow(1 - enter, 3));
                Matrix4x4 matrix = GUI.matrix; Color color = GUI.color;
                GUI.color = color * new Color(1, 1, 1, outAlpha);
                GUI.matrix = matrix * Matrix4x4.Translate(new Vector3(720, 355, 0)) * Matrix4x4.Scale(new Vector3(zoom, zoom, 1)) * Matrix4x4.Translate(new Vector3(-720, -355, 0));
                Slash(new Rect(335, 271, 770, 157), Alpha(Ink, .87f), 82);
                Display(new Rect(258, 174, 940, 314), "K.O.", 277, accent, TextAnchor.MiddleCenter);
                Display(new Rect(244, 165, 940, 314), "K.O.", 277, White, TextAnchor.MiddleCenter);
                GUI.matrix = matrix; GUI.color = color;
                return;
            }
            Slash(new Rect(425, 230, 590, 273), Alpha(Ink, .94f), 32);
            Slash(new Rect(425, 230, 590, 4), accent, 2);
            Text(new Rect(456, 249, 528, 24), demo.KnockoutMode ? "KNOCKOUT / 终局" : "MATCH RESULT", 12, accent, TextAnchor.MiddleCenter, true);
            Display(new Rect(420, 273, 600, 93), frame.matchWinner < 0 ? "DRAW" : $"PLAYER {frame.matchWinner + 1} WINS", 76, White, TextAnchor.MiddleCenter);
            string name = frame.matchWinner < 0 ? "" : demo.SelectedCharacter(frame.matchWinner).displayName;
            Text(new Rect(458, 365, 524, 29), frame.matchWinner < 0 ? frame.matchLabel : name + "   /   " + frame.matchLabel, 17, Muted, TextAnchor.MiddleCenter);
            if (Button(new Rect(590, 420, 260, 48), "再战一局    /    REMATCH", primary: true)) demo.Restart();
            Text(new Rect(500, 475, 440, 20), "R  重新开始     ·     Esc  演出设置", 11, Muted, TextAnchor.MiddleCenter);
        }

        void RoundResult(DuelFrame frame)
        {
            Slash(new Rect(430, 270, 580, 125), Alpha(Ink, .88f), 28);
            Display(new Rect(430, 269, 580, 76), frame.roundWinner < 0 ? "ROUND DRAW" : $"PLAYER {frame.roundWinner + 1} TAKES IT", 51, White, TextAnchor.MiddleCenter);
            Text(new Rect(445, 347, 550, 30), frame.roundLabel, 17, Acid, TextAnchor.MiddleCenter);
        }

        void Loading(DollFightDemo demo)
        {
            Fill(new Rect(0, 0, 1440, 810), Ink);
            Slash(new Rect(-90, 180, 530, 500), Alpha(Pink, .07f), 240);
            Slash(new Rect(1060, 70, 500, 540), Alpha(Cyan, .07f), 240);
            Text(new Rect(100, 185, 1240, 30), "MOTION CAPTURE REHEARSAL", 13, Muted, TextAnchor.MiddleCenter);
            Display(new Rect(100, 230, 1240, 158), "DOLL FIGHT", 134, White, TextAnchor.MiddleCenter);
            Slash(new Rect(615, 390, 210, 5), Pink, 4);
            Text(new Rect(100, 425, 1240, 35), "正在准备对决", 21, White, TextAnchor.MiddleCenter);
            Text(new Rect(200, 472, 1040, 55), demo.status, 14, Muted, TextAnchor.MiddleCenter);
            Fill(new Rect(520, 553, 400, 2), new Color(.16f, .23f, .25f));
            Fill(new Rect(520 + Mathf.PingPong(Time.unscaledTime * 140, 330), 553, 70, 2), Acid);
            Text(new Rect(100, 719, 1240, 28), "LOCAL AVATARS  /  EXPORTED MOTION  /  NATIVE UNITY", 10, Muted, TextAnchor.MiddleCenter);
        }

        void Toolbar(DollFightDemo demo)
        {
            Matrix4x4 old = GUI.matrix;
            float scale = Screen.width / 1440f, height = DuelPresentationLayout.ToolbarHeight(Screen.width) / scale;
            GUI.matrix = Matrix4x4.TRS(new Vector3(0, Screen.height - height * scale, 0), Quaternion.identity, new Vector3(scale, scale, 1));
            Fill(new Rect(0, 0, 1440, height), Ink);
            Fill(new Rect(0, 0, 1440, 1), new Color(.20f, .25f, .29f));
            float y = (height - 34) * .5f;
            bool enabled = GUI.enabled;
            GUI.enabled = enabled && demo.Ready;
            if (Button(new Rect(24, y, 108, 34), demo.playing ? "暂停  Ⅱ" : "播放  ▶", demo.playing)) demo.TogglePlayback();
            if (Button(new Rect(142, y, 96, 34), "重新开始")) demo.Restart();
            Number(new Rect(257, y, 200, 34), $"{Clock(demo.DisplaySeconds(demo.time), false)} / {Clock(demo.DisplaySeconds(demo.RegulationDuration))}", 20, Muted, TextAnchor.MiddleLeft);
            float regulationSeconds = demo.DisplaySeconds(demo.RegulationDuration);
            string regulationLabel = (regulationSeconds <= 60 ? "展示短局 " : "常规对决 ") + Clock(regulationSeconds);
            Text(new Rect(485, y, 455, 34), demo.KnockoutMode ? (demo.CurrentFrame?.overtime == true ? "加时 · HP 归零决胜" : regulationLabel + " · HP 归零决胜") : "三回合对决", 13, Muted, TextAnchor.MiddleCenter);
            if (Button(new Rect(965, y, 134, 34), "玩家视角  V", demo.showPlayerViews)) demo.TogglePlayerViews();
            GUI.enabled = enabled;
            if (Button(new Rect(1111, y, 122, 34), "设置  Esc", SettingsOpen)) SettingsOpen = !SettingsOpen;
            Number(new Rect(1250, y, 165, 34), demo.Ready ? $"{demo.Fps:0} FPS  /  {demo.speed:0.##}×" : "LOADING", 18, Muted, TextAnchor.MiddleRight);
            GUI.matrix = old; GUI.enabled = enabled;
        }

        void Settings(DollFightDemo demo)
        {
            Matrix4x4 old = GUI.matrix; Color oldColor = GUI.color; bool enabled = GUI.enabled;
            float width = 452, height = debugOpen ? 813 : 500;
            float available = Screen.height - DuelPresentationLayout.ToolbarHeight(Screen.width) - 30;
            float scale = Mathf.Min(1, (Screen.width - 32) / width, available / height);
            GUI.color = oldColor * new Color(1, 1, 1, settingsFade);
            Fill(new Rect(0, 0, Screen.width, Screen.height - DuelPresentationLayout.ToolbarHeight(Screen.width)), Alpha(Ink, .24f));
            float slide = (1 - settingsFade) * 28;
            GUI.matrix = Matrix4x4.TRS(new Vector3(Screen.width - (width + 20 - slide) * scale,
                Screen.height - DuelPresentationLayout.ToolbarHeight(Screen.width) - (height + 15) * scale, 0), Quaternion.identity, new Vector3(scale, scale, 1));
            GUI.enabled = enabled && SettingsOpen;
            Fill(new Rect(0, 0, width, height), new Color(.035f, .047f, .065f, .99f));
            Fill(new Rect(0, 0, 4, height), Cyan);
            Text(new Rect(26, 18, 330, 33), "选角与演出", 23, White, bold: true);
            Text(new Rect(27, 50, 330, 22), "CHARACTERS / PRESENTATION", 10, Muted);
            if (Button(new Rect(386, 22, 40, 36), "×")) SettingsOpen = false;
            var feedback = demo.Feedback;
            if (feedback != null)
            {
                if (Button(new Rect(26, 88, 194, 38), "音效  M    " + (feedback.soundEnabled ? "开" : "关"), feedback.soundEnabled)) feedback.soundEnabled = !feedback.soundEnabled;
                if (Button(new Rect(232, 88, 194, 38), "震屏  N    " + (feedback.shakeEnabled ? "开" : "关"), feedback.shakeEnabled)) feedback.shakeEnabled = !feedback.shakeEnabled;
                Text(new Rect(26, 144, 96, 28), "音量", 15, Muted);
                Number(new Rect(363, 144, 63, 28), $"{feedback.volume * 100:0}%", 20, White, TextAnchor.MiddleRight);
                feedback.volume = Slider(new Rect(130, 147, 214, 24), feedback.volume, 1);
                Text(new Rect(26, 187, 96, 28), "反馈强度", 15, Muted);
                Number(new Rect(363, 187, 63, 28), $"{feedback.intensity:0.0}×", 20, White, TextAnchor.MiddleRight);
                feedback.intensity = Slider(new Rect(130, 190, 214, 24), feedback.intensity, 1.5f);
            }
            Fill(new Rect(26, 235, 400, 1), new Color(.20f, .26f, .30f));
            if (demo.Ready)
            {
                if (Button(new Rect(26, 251, 400, 44), "角色选择    /    CHARACTER SELECT", primary: true))
                    demo.OpenCharacterSelection();
                if (Button(new Rect(26, 305, 400, 44), "场地选择    /    STAGE SELECT"))
                    demo.OpenStageSelection();
                Text(new Rect(26, 354, 400, 26), "T  返回角色选择 · 可为双方选择同一角色", 12, Muted);
            }
            Fill(new Rect(26, 391, 400, 1), new Color(.20f, .26f, .30f));
            if (Button(new Rect(26, 407, 400, 38), debugOpen ? "排练工具    −" : "排练工具    +", debugOpen)) debugOpen = !debugOpen;
            if (debugOpen)
            {
                if (Button(new Rect(26, 462, 194, 36), "下一次交锋")) demo.SkipToNextContact();
                if (Button(new Rect(232, 462, 194, 36), "下一次命中")) demo.SkipToNextContact(true);
                if (Button(new Rect(26, 509, 400, 36), "跳至终局")) demo.SkipToFinish();
                if (Button(new Rect(26, 556, 194, 36), "判定体  B", demo.showHitboxes)) demo.showHitboxes = !demo.showHitboxes;
                if (Button(new Rect(232, 556, 194, 36), "自身手脚  H", demo.showSelf)) demo.showSelf = !demo.showSelf;
                if (Button(new Rect(26, 603, 194, 36), "播放速度  " + demo.speed.ToString("0.##") + "×")) demo.CycleSpeed();
                if (feedback != null && Button(new Rect(232, 603, 194, 36), "手柄震动  " + (feedback.hapticsEnabled ? "开" : "关"), feedback.hapticsEnabled)) feedback.hapticsEnabled = !feedback.hapticsEnabled;
                Text(new Rect(26, 655, 400, 26), $"调试时间轴   {demo.DisplaySeconds(demo.time):0.0} / {demo.DisplaySeconds(demo.Duration):0.0}s", 14, Muted);
                float next = Slider(new Rect(26, 693, 400, 24), demo.time, demo.Duration);
                if (Mathf.Abs(next - demo.time) > .001f) demo.Seek(next);
                Text(new Rect(26, 726, 400, 28), demo.CurrentFrame?.intent, 12, Muted);
            }
            Text(new Rect(26, height - 36, 400, 24), "Space  播放    R  重开    V  视角    Esc  关闭", 12, Muted);
            GUI.color = oldColor; GUI.matrix = old; GUI.enabled = enabled;
        }
    }
}
