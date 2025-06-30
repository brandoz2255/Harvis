import os
import google.generativeai as genai
from fastapi import HTTPException
from typing import List, Dict, Any
from google.generativeai.types import FunctionDeclaration

# ─── Gemini Configuration ──────────────────────────────────────────────────────
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
if GEMINI_API_KEY:
    try:
        genai.configure(api_key=GEMINI_API_KEY)
    except Exception as e:
        print(f"Error configuring Gemini API: {e}")

# ─── Tool Definitions ──────────────────────────────────────────────────────────
google_web_search_tool = FunctionDeclaration(
    name="google_web_search",
    description="Performs a web search using Google Search and returns the results.",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The search query"}
        },
        "required": ["query"],
    },
)

# ─── Gemini Interaction ────────────────────────────────────────────────────────
def query_gemini(prompt: str, history: List[Dict[str, Any]]) -> str:
    """
    Sends a prompt and chat history to the Gemini 1.5 Flash model,
    with support for tool use.

    Args:
        prompt: The user's message.
        history: The conversation history.

    Returns:
        The model's response text.

    Raises:
        HTTPException: If the API key is not configured or an API error occurs.
    """
    if not GEMINI_API_KEY:
        raise HTTPException(
            status_code=500, detail="Gemini API key not configured on the server."
        )

    try:
        model = genai.GenerativeModel("gemini-1.5-flash", tools=[google_web_search_tool])

        # Translate history to Gemini's format
        gemini_history = []
        for item in history:
            content = item.get("content")
            role = "user" if item.get("role") == "user" else "model"
            if content and isinstance(content, str):
                gemini_history.append({"role": role, "parts": [{"text": content}]})
            elif isinstance(content, dict) and "tool_code_results" in content:
                # Handle tool results in history
                for result in content["tool_code_results"]:
                    gemini_history.append({"role": role, "parts": [result]})

        chat = model.start_chat(history=gemini_history)
        response = chat.send_message(prompt)

        # Handle tool calls from the model
        if response.tool_calls:
            tool_outputs = []
            for tool_call in response.tool_calls:
                if tool_call.function.name == "google_web_search":
                    search_query = tool_call.function.args["query"]
                    # Execute the actual web search tool
                    search_result = default_api.google_web_search(query=search_query)
                    tool_outputs.append(
                        {"tool_code_results": [{"function_call": tool_call.function, "tool_output": search_result}]}
                    )
                else:
                    tool_outputs.append(
                        {"tool_code_results": [{"function_call": tool_call.function, "tool_output": "Tool not found"}]}
                    )
            # Send tool outputs back to the model
            response = chat.send_message(tool_outputs)

        return response.text
    except Exception as e:
        print(f"Error during Gemini API call: {e}")
        raise HTTPException(
            status_code=500, detail=f"An error occurred with the Gemini API: {e}"
        )


def is_gemini_configured() -> bool:
    """Checks if the Gemini API key is available."""
    return bool(GEMINI_API_KEY)

