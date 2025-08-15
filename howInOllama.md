Using Ollama: Separating Reasoning and Final Output

With Ollama, the approach is conceptually the same, but there are specific implementation options and some nuances to be aware of:
Key Points

    **Ollama models with reasoning ("thinking mode") often output both the internal thought process and the final answer in a single content field, usually using tags like <think>...</think> or similar markers

.

The default Ollama response doesn't always strictly separate reasoning and output unless you use structured outputs or proper extraction methods

    .

Extraction Strategies
1. Use Structured Outputs (Recommended)

    Ollama now supports structured outputs (JSON schemas), allowing you to define a schema with explicit fields for reasoning and final_answer.

    Example schema for an Ollama prompt:

json
{
  "type": "object",
  "properties": {
    "final_answer": { "type": "string" },
    "reasoning": { "type": "string" }
  },
  "required": ["final_answer", "reasoning"]
}

When you submit your prompt using this schema (with the format parameter), the model will return a predictable JSON response that you can directly map on the frontend—showing only final_answer in the chat and reasoning in the AI Insights section

    .

2. Extract From Raw Output (If Not Using Structured Outputs)

    If you're not using structured outputs, manually parse the tokens (e.g., extract text between <think> tags for reasoning, and treat content outside as the final answer).

    This is similar to the Python code shown earlier, and clients must do this themselves since Ollama's API outputs both together and does not enforce a separation for all models

.

Note that models may use different markers, so you may need to customize extraction logic per model

    .

API and Frontend Workflow
Step	Python Backend	TypeScript Frontend
Structured Output	Parse final_answer and reasoning from JSON	Display separately as needed
Raw Model Output	Extract using parsing (e.g., regex on tags)	Display as per separated content
Ollama-Specific Options

    Enable/disable thinking: Some workflows allow toggling reasoning in Ollama's configuration; disabling it returns only clean answers

.

Model-specific behavior: Not all reasoning models use the same markers, so client-side extraction is essential unless you lock down the model and output format

    .

Summary Table
Approach	Pros	Cons
Structured Outputs (JSON schema)	Simple, robust, reliable	Not all models support equally
Manual Parsing of Raw Output	Works with default outputs	May break with model updates

By combining Ollama's structured outputs (where available) or robust client-side parsing, you can easily mirror the backend/frontend split described in your previous workflow: displaying only the final answer in the main chat, and the reasoning (or thought process) exclusively in the AI Insightsghts panel
.
