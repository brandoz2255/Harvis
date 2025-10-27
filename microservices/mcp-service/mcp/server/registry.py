from typing import Callable, Dict, Any, Type
from pydantic import BaseModel, ValidationError
import asyncio

class Tool:
    def __init__(self, name: str, input_model: Type[BaseModel], output_model: Type[BaseModel],
                 scope: str, handler: Callable[[BaseModel], Any], timeout_s: int = 10):
        self.name = name
        self.input_model = input_model
        self.output_model = output_model
        self.scope = scope
        self.handler = handler
        self.timeout_s = timeout_s

registry: Dict[str, Tool] = {}

def register(tool: Tool):
    registry[tool.name] = tool

async def invoke_tool(tool: Tool, args: dict):
    try:
        in_obj = tool.input_model(**args)
    except ValidationError as ve:
        raise ValueError(f"Invalid args: {ve}")

    async def run():
        out = await tool.handler(in_obj)
        return tool.output_model(**out)
    return await asyncio.wait_for(run(), timeout=tool.timeout_s)
