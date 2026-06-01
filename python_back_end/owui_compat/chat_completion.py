"""Bridge OWUI chat-completions to Harvis's model_proxy, in-process.

The facade authenticates the user (JWT, via ``get_current_user``) and then hands
a cleaned OpenAI body to ``model_proxy.execute_chat_completion`` — reusing
Harvis's full model-routing brain (Moonshot/NVIDIA/Ollama selection, auto-model
resolution, tool-call rescue, SSE) WITHOUT the shared-gateway-token check that
the public ``/v1/chat/completions`` route enforces. model_proxy already emits
OpenAI ``chat.completion.chunk`` SSE, which is exactly what OWUI's stream parser
consumes — so the StreamingResponse passes straight through.
"""

from __future__ import annotations

from .translate import owui_body_to_proxy


async def run_chat_completion(request, owui_body: dict):
    # Lazy import keeps this package free of import-time coupling to the
    # workspace package (avoids any chance of a circular import at load).
    from workspace.model_proxy import execute_chat_completion

    proxy_body = owui_body_to_proxy(owui_body)
    return await execute_chat_completion(request, proxy_body)
