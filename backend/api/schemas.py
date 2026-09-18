from pydantic import BaseModel
from typing import List


class BatteryConfig(BaseModel):
    capacity: float
    initial: float
    max_charge: float
    max_discharge: float



class OptimizeRequest(BaseModel):

    operator_note: str

    demand: List[float]

    solar: List[float]

    tariff: List[float]

    battery: BatteryConfig



class OptimizeResponse(BaseModel):

    status: str

    total_cost_bdt: float

    applied_directives: list

    battery_summary: dict

    hourly_plan: list