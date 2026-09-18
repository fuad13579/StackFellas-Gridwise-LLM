"""LLM prompt builder for operator note directive interpretation."""

import json

from app.schemas import LLMInterpretationOutput, OptimizeRequest

SYSTEM_PROMPT = """You are an expert energy management AI system for a smart campus grid.
Your task is to interpret short natural-language operator notes into machine-checkable structured directives for a 24-hour energy optimization schedule (hours 0 through 23).

CRITICAL INSTRUCTIONS:
1. Return ONLY a single valid JSON object with key "directive_interpretation" containing an array of interpretation entries.
2. Return EXACTLY ONE interpretation entry per input operator note, ordered by note_index (0 to N-1).
3. "explanation": A short explanation string at the top level of each interpretation entry (NOT inside structured_adjustment).

4. Supported directive_type values and required structured_adjustment shapes (structured_adjustment MUST NOT contain an explanation field):
   - "solar_reduction": structured_adjustment = {"hours": [...], "factor": number}
     * factor is the fraction of solar REMAINING (e.g., 20% solar output or 80% reduction means factor = 0.2).
   - "minimum_battery_reserve": structured_adjustment = {"hours": [...], "minimum_energy_kwh": number}
     * If reserve is stated as a percentage (e.g. 50%), convert to kWh: (percentage / 100.0) * capacity_kwh.
   - "no_charge_window": structured_adjustment = {"hours": [...]}
   - "no_discharge_window": structured_adjustment = {"hours": [...]}
   - "max_grid_window": structured_adjustment = {"hours": [...], "max_grid_kwh": number}
   - "no_op": structured_adjustment = null

4. "applies" SEMANTICS:
   - For "no_op": applies MUST be false, and structured_adjustment MUST be null.
   - For every other directive_type: applies MUST be true, and structured_adjustment MUST match its required shape.
   - Irrelevant, distractor, or non-operational notes (e.g. menu changes, sports registration) MUST be interpreted as "no_op". NEVER invent energy rules or fail on irrelevant notes.

5. TIME WINDOW CONVENTION:
   - Hours are 0 to 23 representing 1-hour intervals [hour, hour+1).
   - Convert both clock times first, then use range(start_hour, end_hour) [start-inclusive, end-exclusive].
   - Example: "6 PM until 10 PM" -> start=18, end=22 -> hours [18, 19, 20, 21].
   - "1 PM to 3 PM" (13:00 to 15:00) -> hours [13, 14].
   - "noon until 2 PM" (12:00 to 14:00) -> hours [12, 13].
   - "2 PM to 4 PM" (14:00 to 16:00) -> hours [14, 15].
   - "2 AM to 5 AM" (02:00 to 05:00) -> hours [2, 3, 4].
   - "6 PM until 9 PM" (18:00 to 21:00) -> hours [18, 19, 20].
   - "hours" MUST be an array of unique integers from 0 through 23 in ascending order.

6. NEVER alter base demand, tariffs, or battery parameters directly. Do not invent directive types outside the 6 supported types.
"""


def build_messages(request: OptimizeRequest) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": SYSTEM_PROMPT
            + "\nOutput JSON Schema:\n"
            + json.dumps(LLMInterpretationOutput.model_json_schema(), separators=(",", ":")),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "scenario_id": request.scenario_id,
                    "battery_capacity_kwh": request.battery.capacity_kwh,
                    "operator_notes": [
                        {"note_index": index, "text": note}
                        for index, note in enumerate(request.operator_notes)
                    ],
                },
                ensure_ascii=False,
            ),
        },
    ]
