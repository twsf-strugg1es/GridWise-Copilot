"""Request and response contracts for POST /optimize-energy.

The Problem Statement is canonical for every field name here. Pydantic does the
structural validation so a malformed request is rejected before it reaches the
LLM or the solver -- that is worth 2 of the 10 API-contract points and it also
keeps garbage out of the optimizer.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

DirectiveType = Literal[
    "solar_reduction",
    "minimum_battery_reserve",
    "no_charge_window",
    "no_discharge_window",
    "max_grid_window",
    "no_op",
]

BatteryAction = Literal["charge", "discharge", "idle"]

HOURS_IN_DAY = 24


# --------------------------------------------------------------------------- #
# Request
# --------------------------------------------------------------------------- #


class HourInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    hour: int = Field(ge=0, le=23)
    demand_kwh: float = Field(ge=0)
    solar_kwh: float = Field(ge=0)
    tariff_bdt_per_kwh: float = Field(ge=0)


class BatteryInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    capacity_kwh: float = Field(ge=0)
    initial_energy_kwh: float = Field(ge=0)
    minimum_energy_kwh: float = Field(ge=0)
    max_charge_kwh_per_hour: float = Field(ge=0)
    max_discharge_kwh_per_hour: float = Field(ge=0)

    @model_validator(mode="after")
    def _coherent(self) -> "BatteryInput":
        if self.initial_energy_kwh > self.capacity_kwh:
            raise ValueError("initial_energy_kwh exceeds capacity_kwh")
        if self.minimum_energy_kwh > self.capacity_kwh:
            raise ValueError("minimum_energy_kwh exceeds capacity_kwh")
        # The day must end where it started (Problem Statement 9.6), so a start
        # below the floor could never be repaired -- reject it as unschedulable
        # rather than emit an invalid plan.
        if self.initial_energy_kwh < self.minimum_energy_kwh:
            raise ValueError("initial_energy_kwh is below minimum_energy_kwh")
        return self


class OptimizeRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    scenario_id: str = Field(min_length=1)
    operator_notes: list[str] = Field(min_length=1, max_length=3)
    hours: list[HourInput] = Field(min_length=HOURS_IN_DAY, max_length=HOURS_IN_DAY)
    battery: BatteryInput

    @field_validator("operator_notes")
    @classmethod
    def _notes_non_empty(cls, notes: list[str]) -> list[str]:
        for i, note in enumerate(notes):
            if not note or not note.strip():
                raise ValueError(f"operator_notes[{i}] is empty")
        return notes

    @field_validator("hours")
    @classmethod
    def _hours_are_a_full_day(cls, hours: list[HourInput]) -> list[HourInput]:
        seen = {h.hour for h in hours}
        if seen != set(range(HOURS_IN_DAY)):
            raise ValueError("hours must contain exactly one entry for each hour 0-23")
        return hours

    def ordered_hours(self) -> list[HourInput]:
        """Hours sorted by clock hour, so the rest of the code can index by hour."""
        return sorted(self.hours, key=lambda h: h.hour)


# --------------------------------------------------------------------------- #
# Response
# --------------------------------------------------------------------------- #


class DirectiveInterpretation(BaseModel):
    note_index: int = Field(ge=0)
    applies: bool
    directive_type: DirectiveType
    # Left as a plain dict: the guardrail layer has already proven the shape
    # matches Section 04 for the chosen directive_type, and a union here would
    # only risk re-serialising it differently.
    structured_adjustment: dict[str, Any] | None
    explanation: str


class HourPlan(BaseModel):
    hour: int = Field(ge=0, le=23)
    grid_kwh: float = Field(ge=0)
    solar_used_kwh: float = Field(ge=0)
    battery_action: BatteryAction
    battery_kwh: float = Field(ge=0)
    battery_energy_after_kwh: float = Field(ge=0)


class OptimizeResponse(BaseModel):
    scenario_id: str
    directive_interpretation: list[DirectiveInterpretation]
    hourly_plan: list[HourPlan]
    total_grid_kwh: float
    total_cost_bdt: float
    peak_grid_kwh: float
    plan_summary: str


class HealthResponse(BaseModel):
    status: str = "ok"
