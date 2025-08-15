
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Input, Static
from textual.containers import ScrollableContainer
from vibe_agent import VibeAgent

class VibeTUI(App):
    BINDINGS = [("q", "quit", "Quit")]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Initialize the agent with the current directory
        self.agent = VibeAgent(project_dir=os.getcwd())

    def compose(self) -> ComposeResult:
        yield Header()
        yield ScrollableContainer(Static("Agent Ready.", id="agent_status"), id="output")
        yield Input(placeholder="Enter your command or 'vibe' for vibe mode...")
        yield Footer()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        command = event.value
        output_widget = self.query_one("#output", ScrollableContainer)
        output_widget.mount(Static(f"> {command}"))
        self.query_one(Input).value = ""

        # Process command through the agent
        response_text, _ = self.agent.process_command(command)

        # Display the agent's response
        output_widget.mount(Static(response_text))
        output_widget.scroll_end()

if __name__ == "__main__":
    app = VibeTUI()
    app.run()
