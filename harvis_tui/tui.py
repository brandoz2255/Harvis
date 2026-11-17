"""
Harvis TUI - Terminal User Interface

A Textual-based terminal interface for interacting with Harvis.
"""

from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Input, Button, Static, DataTable
from textual.containers import Container, ScrollableContainer
from textual.reactive import reactive
from textual.binding import Binding
import httpx
import asyncio
from typing import List


class MessageWidget(Static):
    """Widget to display a chat message."""
    
    def __init__(self, content: str, is_user: bool = False, **kwargs):
        super().__init__(**kwargs)
        self.content = content
        self.is_user = is_user
        self.stylesheet = "user-msg" if is_user else "ai-msg"


class HarvisTUI(App):
    """Harvis TUI Application."""
    
    CSS = """
    Screen {
        background: $surface;
    }
    
    #chat-container {
        height: 1fr;
        border: thick $primary;
        padding: 1;
    }
    
    .user-msg {
        background: $primary-lighten-1;
        color: $text;
        padding: 1;
        margin: 0 0 1 0;
        width: 70%;
        align: right;
    }
    
    .ai-msg {
        background: $secondary-lighten-1;
        color: $text;
        padding: 1;
        margin: 0 0 1 0;
        width: 70%;
        align: left;
    }
    
    #input-container {
        height: auto;
        border-top: heavy $primary;
        padding: 1;
    }
    
    #message-input {
        width: 100%;
    }
    
    #welcome-screen {
        text-align: center;
        vertical-align: middle;
        content-align: center;
    }
    
    .title {
        text-style: bold;
        text-align: center;
        color: $primary;
    }
    """
    
    BINDINGS = [
        Binding("enter", "send_message", "Send"),
        Binding("ctrl+l", "clear_screen", "Clear"),
        Binding("q", "quit", "Quit"),
        Binding("f1", "help", "Help"),
    ]
    
    messages: List[str] = reactive([])
    backend_url = "http://localhost:8001"
    session_id: str = None
    
    def compose(self) -> ComposeResult:
        """Compose the UI."""
        yield Header()
        
        with ScrollableContainer(id="chat-container"):
            yield Static(
                """[bold green]═══ Harvis TUI ═══[/bold green]

[bold]Welcome to Harvis![/bold] 🌶️

[italic]Your terminal interface to the AI assistant.[/italic]

Type your message below and press [blue]Enter[/blue] to send.

[dim]Press F1 for help • Q to quit[/dim]""",
                id="welcome-screen"
            )
        
        with Container(id="input-container"):
            yield Input(
                placeholder="Type your message... (Ctrl+L to clear, Q to quit)",
                id="message-input"
            )
        
        yield Footer()
    
    async def on_mount(self) -> None:
        """Initialize the app."""
        # Connect to backend
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{self.backend_url}/tui/connect")
                self.session_id = response.json().get("session_id")
        except Exception as e:
            self.notify(f"Could not connect to backend: {e}", severity="error")
    
    async def action_send_message(self) -> None:
        """Send a message to the backend."""
        input_widget = self.query_one("#message-input", Input)
        message = input_widget.value.strip()
        
        if not message:
            return
        
        # Clear input
        input_widget.value = ""
        
        # Add user message to display
        self.messages.append(f"> {message}")
        self.refresh_messages()
        
        # Send to backend
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.backend_url}/tui/chat",
                    json={"session_id": self.session_id, "message": message}
                )
                data = response.json()
                ai_response = data.get("response", "No response")
                self.messages.append(f"🤖 {ai_response}")
                self.refresh_messages()
        except Exception as e:
            self.notify(f"Error: {e}", severity="error")
    
    def refresh_messages(self) -> None:
        """Refresh the messages display."""
        welcome_screen = self.query_one("#welcome-screen", Static)
        welcome_screen.mount_after(
            Static("\n".join(self.messages))
        )
        # Scroll to bottom
        chat_container = self.query_one("#chat-container", ScrollableContainer)
        chat_container.scroll_end(animate=False)
    
    async def action_clear_screen(self) -> None:
        """Clear the screen."""
        self.messages = []
        self.refresh_messages()
        self.notify("Screen cleared")
    
    async def action_help(self) -> None:
        """Show help."""
        self.popup_dialog(
            Static("""[bold]Harvis TUI - Help[/bold]

[bold]Keyboard Shortcuts:[/bold]
  [blue]Enter[/blue]  - Send message
  [blue]Ctrl+L[/blue] - Clear screen
  [blue]Q[/blue]    - Quit
  [blue]F1[/blue]   - Show this help

[bold]Commands:[/bold]
  [green]help[/green]     - Show help
  [green]workspaces[/green] - List workspaces
  [green]files[/green]    - List files
  [green]exit[/green]     - Disconnect

[italic]Built with Textual & FastAPI[/italic]""")
        )


if __name__ == "__main__":
    app = HarvisTUI()
    app.run()
