from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from tazama.mcp.contracts import PatientObservations


class DeterminePriorityRequest(BaseModel):
    """Versioned request for the SATS priority.

    signs is the list of sign ids the nurse has identified:
      None -> the nurse has not assessed signs yet
      []   -> the nurse assessed and found none
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal["1.0"] = "1.0"
    case_id: str = Field(min_length=1)
    observations: PatientObservations
    signs: list[str] | None = None