import ast
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
            stripped = v.strip()
            if stripped == "":
                return {}

            # Try JSON first
            try:
                return json.loads(stripped)
            except json.JSONDecodeError:
                # Fallback: Python dict-style string
                try:
                    print("FALLING BACK")
                    return ast.literal_eval(stripped)
                except Exception:
                    raise ValueError(f"Invalid arguments string: {stripped}")
        return v
