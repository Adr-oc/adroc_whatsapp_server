from pydantic import BaseModel


class LogsResponse(BaseModel):
    lines: list[str]
