from pydantic import BaseModel, ConfigDict, Field


class InventoryItem(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str = Field(min_length=1, max_length=200)
    count: int = Field(ge=0, le=10_000)
    confidence: float = Field(ge=0.0, le=1.0)


class CVResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    items: list[InventoryItem]
