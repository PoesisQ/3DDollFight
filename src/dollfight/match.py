"""Deterministic round adjudication, independent of poses and presentation."""

REASONS = {"ko": "KO", "double_ko": "双 KO", "timeout": "时间结束"}
KNOCKOUT_REGULATION_SECONDS = 135.0


def knockout_match_result(verdict, *, overtime=False):
    """A regulation clock never adjudicates a knockout-only match."""
    finished = verdict is not None
    winner = verdict["winner"] if finished else -1
    return {
        "state": "finished" if finished else "active",
        "winner": winner,
        "wins": [int(finished and winner == player) for player in range(2)],
        "rounds": 1,
        "label": ("双方倒地 · 双 KO" if winner < 0 else f"P{winner + 1} 获胜 · KO")
        if finished
        else "加时 · KO 决胜"
        if overtime
        else "单局 · KO 决胜",
    }


def round_result(number, health, time_s, *, timeout=False):
    """Return an immutable-by-convention result only once the round has ended."""
    hp = list(health)
    reason = (
        "double_ko" if hp[0] == hp[1] == 0 else "ko" if 0 in hp else "timeout" if timeout else None
    )
    if reason is None:
        return None
    winner = -1 if hp[0] == hp[1] else int(hp[1] > hp[0])
    verdict = "平局" if winner < 0 else f"P{winner + 1} 获胜"
    return {
        "round": number,
        "health": hp,
        "winner": winner,
        "reason": reason,
        "time_s": round(float(time_s), 4),
        "label": f"第 {number} 回合{verdict} · {REASONS[reason]}",
    }


def match_result(rounds, total_rounds):
    """Aggregate completed rounds without exposing any future result."""
    wins = [sum(r["winner"] == p for r in rounds) for p in range(2)]
    finished = len(rounds) == total_rounds
    winner = -1 if not finished or wins[0] == wins[1] else int(wins[1] > wins[0])
    score = f"{wins[0]} : {wins[1]}"
    label = (
        f"比赛平局 · {score}"
        if finished and winner < 0
        else f"P{winner + 1} 赢得比赛 · {score}"
        if finished
        else f"比分 {score}"
    )
    return {
        "state": "finished" if finished else "active",
        "winner": winner,
        "wins": wins,
        "rounds": total_rounds,
        "label": label,
    }


def round_schedule(frames, duration, *, fps=30):
    """Use authored round markers when present, otherwise a 30-second clock.

    The last sample represents the end of its playback interval: its snapshot
    must contain the verdict even when the nominal 30 s boundary has no pose.
    """
    start = float(frames[0]["t"])
    end = float(max(duration, frames[-1]["t"]))
    authored = all("round" in f.get("performance", {}) for f in frames)
    schedule, numbers = [], []
    for index, frame in enumerate(frames):
        number = (
            int(frame["performance"]["round"])
            if authored
            else int(min(frame["t"] - start, max(0, end - start - 1e-7)) // 30) + 1
        )
        numbers.append(number)
        if not schedule or number != schedule[-1]["round"]:
            if schedule:
                if authored:
                    schedule[-1]["end"] = min(schedule[-1]["end"], float(frame["t"]))
                schedule[-1]["last_index"] = index - 1
            begin = float(frame["t"]) if authored else start + (number - 1) * 30
            schedule.append(
                {
                    "round": number,
                    "start": begin,
                    "end": begin + 30 if authored else min(begin + 30, end),
                    "last_index": len(frames) - 1,
                }
            )
    if authored:
        # Pipeline duration is the last pose timestamp, one sample before the
        # nominal endpoint for a complete rehearsal. Preserve that endpoint
        # only when the difference fits within one known sample interval.
        nominal_end = schedule[-1]["end"]
        if not 0 <= nominal_end - end <= 1 / fps + 1e-7:
            schedule[-1]["end"] = min(nominal_end, end)
    return schedule, numbers
