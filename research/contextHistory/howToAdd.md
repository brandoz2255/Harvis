To ensure your Python backend with Ollama remembers context within a chat thread, you should maintain a list of message exchanges and pass this evolving list to each API call. Ollama's Python library supports this pattern using the messages parameter, structured as a list of dictionaries with "role" and "content"

.

Here’s the proper structure and workflow:

    Maintain a conversation history list, where each message in the chat (user or assistant) is an element with the following format:

python
{"role": "user" or "assistant", "content": "The message text"}

Append each new message to this list as it arrives (i.e., when the user sends a message, append their input with 'role': 'user'; after the AI responds, append the AI reply with 'role': 'assistant')

.

Call Ollama’s chat endpoint with the entire conversation history for every request:

python
import ollama

conversation_history = [
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "Hello!"},
    {"role": "assistant", "content": "Hi, how can I help you?"},
    # ...more exchanges
]

# Add the next user input
conversation_history.append({"role": "user", "content": "What's the capital of France?"})

# Get the AI's response
response = ollama.chat(
    model="llama3.1",  # or your preferred model
    messages=conversation_history
)
ai_reply = response['message']['content']
conversation_history.append({"role": "assistant", "content": ai_reply})

Repeat this process for every new user message, always injecting the up-to-date conversation history into the prompt until the thread ends or the history is cleared

    .

    Manage history length if necessary by trimming old exchanges so you don’t exceed Ollama’s context (token) limit.

This method gives the AI access to recent chat context, resulting in responses that reference earlier messages in the thread

.

You can implement this pattern either in a class structure (see example below) or with plain variables:

python
import ollama

class OllamaChat:
    def __init__(self, model_name="llama3.1"):
        self.model_name = model_name
        self.conversation_history = [
            # Optionally, add a 'system' prompt here
        ]
    def send_message(self, message):
        self.conversation_history.append({'role': 'user', 'content': message})
        response = ollama.chat(
            model=self.model_name,
            messages=self.conversation_history
        )
        ai_reply = response['message']['content']
        self.conversation_history.append({'role': 'assistant', 'content': ai_reply})
        return ai_reply

    def clear_history(self):
        self.conversation_history = []

This pattern is the established way to provide conversational memory to LLMs using Ollama’s Python API
.
