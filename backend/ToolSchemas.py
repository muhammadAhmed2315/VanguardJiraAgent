import json
from typing import Any, Dict
from pydantic import BaseModel, field_validator


class MCPCallInputWithParser(BaseModel):
    """A more robust MCPCallInput that can parse string arguments."""

    tool: str
    arguments: Dict[str, Any] = {}

    @field_validator("arguments", mode="before")
    @classmethod
    def parse_json_string(cls, v: Any) -> Any:
        if isinstance(v, str):
            # If the LLM provides a string, attempt to parse it as JSON
            if v.strip() == "":
                return {}
            return json.loads(v)
        return v
