"""Prompt for operator-note interpretation.

Two rules cause almost every wrong answer on this challenge and both are stated
here twice on purpose:

  * time windows are start-inclusive and END-EXCLUSIVE  -> 1 PM to 3 PM is [13, 14]
  * `factor` is the fraction of solar that REMAINS      -> an 80% drop is 0.2

The few-shot block deliberately paraphrases the same directive several different
ways, because hidden cases reword the same rule and the model must generalise
rather than pattern-match one phrasing.
"""

SYSTEM_PROMPT = """\
You convert campus energy operator notes into strict JSON directives for an \
optimizer. You never invent demand, solar, tariff or battery numbers, and you \
never invent a directive type outside the six listed below.

Return ONLY a JSON object of this exact shape:

{"directive_interpretation": [
  {"note_index": <int>, "applies": <bool>, "directive_type": <string>,
   "structured_adjustment": <object|null>, "explanation": <short string>}
]}

Return exactly one entry per operator note, in note_index order starting at 0.

THE SIX DIRECTIVE TYPES AND THEIR REQUIRED structured_adjustment:

1. solar_reduction          {"hours": [ints], "factor": number 0..1}
   Usable solar is reduced during specific hours. `factor` is the fraction of
   the forecast that REMAINS, not the amount lost.
     "drops to 20%"          -> factor 0.2
     "an 80% reduction"      -> factor 0.2
     "about one fifth"       -> factor 0.2
     "roughly a quarter"     -> factor 0.25
     "cut in half"           -> factor 0.5
     "panels offline"        -> factor 0.0

2. minimum_battery_reserve  {"hours": [ints], "minimum_energy_kwh": number}
   Battery energy must stay at or above a stated level during those hours.

3. no_charge_window         {"hours": [ints]}
   The battery may not charge during those hours.

4. no_discharge_window      {"hours": [ints]}
   The battery may not discharge during those hours.

5. max_grid_window          {"hours": [ints], "max_grid_kwh": number}
   Grid import must not exceed a stated amount in each of those hours.

6. no_op                    null
   The note has nothing to do with today's 24-hour energy schedule. Use this for
   catering, staffing, admin, deadlines, events, maintenance of unrelated
   equipment, or anything about a different day.

HOURS RULES:
  * Hours are whole numbers 0 through 23 on a 24-hour clock, unique, ascending.
  * A window is START-INCLUSIVE and END-EXCLUSIVE.
      "1 PM to 3 PM"         -> [13, 14]
      "noon until 2 PM"      -> [12, 13]
      "between 14:00 and 18:00" -> [14, 15, 16, 17]
      "from 6 PM until 9 PM" -> [18, 19, 20]
      "during the 9 AM hour" -> [9]
      "overnight, 10 PM to 2 AM" -> [22, 23, 0, 1]
  * If a note gives no time window but clearly applies all day, use all 24 hours.

applies RULES:
  * no_op          -> "applies": false and "structured_adjustment": null
  * every other type -> "applies": true and a structured_adjustment matching the
    shape above exactly.

If a note is ambiguous, choose the single directive type that best matches its
operational meaning. Never emit two entries for one note. Never emit a type that
is not in the list. Keep each explanation to one short sentence.
"""

FEW_SHOT_USER = """\
Operator notes:
[0] "Facilities will wash the rooftop solar panels from noon until 2 PM. During cleaning, usable solar should be treated as roughly 25% of the forecast."
[1] "The sports office moved next month's registration deadline."
[2] "Keep at least 120 kWh in the battery from 6 PM until 9 PM for the evening event."
"""

FEW_SHOT_ASSISTANT = """\
{"directive_interpretation": [
  {"note_index": 0, "applies": true, "directive_type": "solar_reduction",
   "structured_adjustment": {"hours": [12, 13], "factor": 0.25},
   "explanation": "Panel cleaning leaves 25% of forecast solar from noon to 2 PM."},
  {"note_index": 1, "applies": false, "directive_type": "no_op",
   "structured_adjustment": null,
   "explanation": "An administrative deadline does not affect today's energy schedule."},
  {"note_index": 2, "applies": true, "directive_type": "minimum_battery_reserve",
   "structured_adjustment": {"hours": [18, 19, 20], "minimum_energy_kwh": 120},
   "explanation": "Battery must hold at least 120 kWh through the evening event."}
]}"""

FEW_SHOT_USER_2 = """\
Operator notes:
[0] "Expect an 80% reduction in rooftop PV between 13:00 and 15:00 for the maintenance window."
[1] "The inverter service crew needs charging paused between 2 PM and 4 PM, and please do not pull more than 150 kWh from the grid during that same window."
"""

FEW_SHOT_ASSISTANT_2 = """\
{"directive_interpretation": [
  {"note_index": 0, "applies": true, "directive_type": "solar_reduction",
   "structured_adjustment": {"hours": [13, 14], "factor": 0.2},
   "explanation": "An 80% PV reduction leaves 20% usable solar from 13:00 to 15:00."},
  {"note_index": 1, "applies": true, "directive_type": "no_charge_window",
   "structured_adjustment": {"hours": [14, 15]},
   "explanation": "Battery charging is unavailable during the inverter service window."}
]}"""


def build_user_prompt(notes: list[str]) -> str:
    lines = ["Operator notes:"]
    for index, note in enumerate(notes):
        lines.append(f'[{index}] "{note.strip()}"')
    lines.append("")
    lines.append(
        f"Return exactly {len(notes)} directive_interpretation "
        f"{'entry' if len(notes) == 1 else 'entries'}, note_index 0 to {len(notes) - 1}."
    )
    return "\n".join(lines)


def build_messages(notes: list[str], repair_hint: str | None = None) -> list[dict]:
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": FEW_SHOT_USER},
        {"role": "assistant", "content": FEW_SHOT_ASSISTANT},
        {"role": "user", "content": FEW_SHOT_USER_2},
        {"role": "assistant", "content": FEW_SHOT_ASSISTANT_2},
        {"role": "user", "content": build_user_prompt(notes)},
    ]
    if repair_hint:
        # Second attempt: hand the model its own failure so it can correct the
        # one field that broke rather than re-rolling the whole answer.
        messages.append(
            {
                "role": "user",
                "content": (
                    "Your previous answer was rejected by the validator with this "
                    f"error:\n{repair_hint}\n"
                    "Return the corrected JSON object only."
                ),
            }
        )
    return messages
