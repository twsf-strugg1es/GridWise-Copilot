from pydantic import BaseModel
from typing import List


class HourData(BaseModel):
    hour: int
    demand_kwh: float
    solar_kwh: float
    tariff_bdt_per_kwh: float


class BatteryConfig(BaseModel):
    capacity_kwh: float
    initial_energy_kwh: float
    max_charge_kwh: float
    max_discharge_kwh: float


class OptimizationRequest(BaseModel):
    scenario_id: str
    operator_notes: List[str]
    hours: List[HourData]
    battery: BatteryConfig