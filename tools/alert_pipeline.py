from pydantic import BaseModel, Field

class EnrichedAlert(BaseModel):
    """
    Represents an enriched alert with various fields.
    """

    timestamp: str = Field(..., description="The timestamp of the alert.")
    src_ip: str = Field(..., description="The source IP address of the alert.")
    dst_ip: str = Field(..., description="The destination IP address of the alert.")
    rule_name: str = Field(..., description="The name of the alert rule.")
    original_severity: str = Field(..., description="The original severity of the alert.")
    normalized_severity: str = Field(..., description="The normalized severity of the alert.")
    is_malicious_ip: bool = Field(..., description="Indicates if the IP is malicious.")
    mitre_technique: str = Field(..., description="The MITRE ATT&CK technique associated with the alert.")
