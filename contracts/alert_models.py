from datetime import datetime
from typing import List
from pydantic import BaseModel


class Alert(BaseModel):
    alert_id: str
    timestamp: datetime
    severity: str
    description: str


class EnrichedAlert(Alert):
    llm_analysis: str
    mitre_techniques: List[str]
    false_positive_likelihood: float
