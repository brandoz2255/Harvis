#!/usr/bin/env python3
"""
OpenClaw Configuration TUI Tool
A terminal user interface for managing OpenClaw settings
"""

import curses
import json
import os
import subprocess
import sys
from pathlib import Path


class OpenClawTUI:
    def __init__(self):
        self.config_path = Path.home() / ".openclaw" / "openclaw.json"
        self.config = {}
        self.current_menu = "main"
        self.selected_item = 0
        self.menu_items = []
        self.message = ""
        self.load_config()

    def load_config(self):
        """Load existing config or create default"""
        if self.config_path.exists():
            try:
                with open(self.config_path, "r") as f:
                    self.config = json.load(f)
            except:
                self.config = self.get_default_config()
        else:
            self.config = self.get_default_config()

    def save_config(self):
        """Save config to file"""
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_path, "w") as f:
                json.dump(self.config, f, indent=2)
            return True
        except Exception as e:
            self.message = f"Error saving: {e}"
            return False

    def get_default_config(self):
        """Return default configuration"""
        return {
            "gateway": {"mode": "local", "port": 18789},
            "channels": {"discord": {"enabled": False, "token": ""}},
            "agents": {
                "defaults": {"maxConcurrent": 4, "subagents": {"maxConcurrent": 8}}
            },
            "messages": {"ackReactionScope": "group-mentions"},
            "plugins": {"entries": {}},
        }

    def get_menu_items(self):
        """Get menu items based on current menu"""
        if self.current_menu == "main":
            return [
                ("🚀 Quick Start", "quickstart"),
                ("⚙️  Gateway Settings", "gateway"),
                ("💬 Discord Integration", "discord"),
                ("🤖 Agent Settings", "agents"),
                ("📡 View Current Config", "view"),
                ("💾 Save Configuration", "save"),
                ("🔄 Restart OpenClaw", "restart"),
                ("📊 View Status", "status"),
                ("❌ Exit", "exit"),
            ]
        elif self.current_menu == "gateway":
            return [
                (
                    f"Mode: {self.config.get('gateway', {}).get('mode', 'local')}",
                    "mode",
                ),
                (f"Port: {self.config.get('gateway', {}).get('port', 18789)}", "port"),
                ("🔙 Back to Main Menu", "main"),
            ]
        elif self.current_menu == "discord":
            enabled = (
                self.config.get("channels", {}).get("discord", {}).get("enabled", False)
            )
            token = self.config.get("channels", {}).get("discord", {}).get("token", "")
            return [
                (f"Enabled: {'✅ Yes' if enabled else '❌ No'}", "toggle"),
                (
                    f"Token: {'*' * min(len(token), 20)}..."
                    if token
                    else "Token: Not set",
                    "token",
                ),
                ("🔙 Back to Main Menu", "main"),
            ]
        elif self.current_menu == "agents":
            max_concurrent = (
                self.config.get("agents", {})
                .get("defaults", {})
                .get("maxConcurrent", 4)
            )
            subagent_max = (
                self.config.get("agents", {})
                .get("defaults", {})
                .get("subagents", {})
                .get("maxConcurrent", 8)
            )
            return [
                (f"Max Concurrent Agents: {max_concurrent}", "max_concurrent"),
                (f"Max Subagents: {subagent_max}", "subagent_max"),
                ("🔙 Back to Main Menu", "main"),
            ]
        return []

    def draw_header(self, stdscr):
        """Draw the header"""
        height, width = stdscr.getmaxyx()
        header = "🦞 OPENCLAW CONFIGURATION TOOL"
        stdscr.addstr(
            0, (width - len(header)) // 2, header, curses.A_BOLD | curses.COLOR_BLUE
        )
        stdscr.addstr(1, 0, "=" * width)

        if self.message:
            stdscr.addstr(2, 0, f"ℹ️  {self.message}"[: width - 1], curses.COLOR_YELLOW)

    def draw_menu(self, stdscr):
        """Draw the menu"""
        height, width = stdscr.getmaxyx()
        self.menu_items = self.get_menu_items()

        start_y = 4
        for idx, (label, _) in enumerate(self.menu_items):
            x = 4
            y = start_y + idx

            if y >= height - 2:
                break

            if idx == self.selected_item:
                stdscr.addstr(y, x, f"> {label}", curses.A_REVERSE | curses.COLOR_GREEN)
            else:
                stdscr.addstr(y, x, f"  {label}")

        # Draw footer
        footer_y = height - 2
        stdscr.addstr(footer_y, 0, "-" * width)
        stdscr.addstr(
            footer_y + 1, 0, "↑↓ Navigate | Enter Select | Q Quit", curses.COLOR_CYAN
        )

    def handle_input(self, stdscr, key):
        """Handle user input"""
        if key == curses.KEY_UP and self.selected_item > 0:
            self.selected_item -= 1
        elif key == curses.KEY_DOWN and self.selected_item < len(self.menu_items) - 1:
            self.selected_item += 1
        elif key == ord("\n") or key == curses.KEY_ENTER:
            self.handle_selection(stdscr)
        elif key == ord("q") or key == ord("Q"):
            return False
        return True

    def handle_selection(self, stdscr):
        """Handle menu selection"""
        if not self.menu_items:
            return

        action = self.menu_items[self.selected_item][1]

        if action == "exit":
            sys.exit(0)
        elif action == "main":
            self.current_menu = "main"
            self.selected_item = 0
        elif action in ["gateway", "discord", "agents"]:
            self.current_menu = action
            self.selected_item = 0
        elif action == "quickstart":
            self.show_quickstart(stdscr)
        elif action == "view":
            self.show_config(stdscr)
        elif action == "save":
            self.save_config()
            self.message = "Configuration saved!"
        elif action == "restart":
            self.restart_openclaw()
            self.message = "OpenClaw restarted!"
        elif action == "status":
            self.show_status(stdscr)
        elif action == "mode":
            self.edit_gateway_mode(stdscr)
        elif action == "port":
            self.edit_gateway_port(stdscr)
        elif action == "toggle":
            self.toggle_discord()
        elif action == "token":
            self.edit_discord_token(stdscr)
        elif action == "max_concurrent":
            self.edit_max_concurrent(stdscr)
        elif action == "subagent_max":
            self.edit_subagent_max(stdscr)

    def show_quickstart(self, stdscr):
        """Show quick start guide"""
        curses.endwin()
        os.system("clear")
        print("""
╔════════════════════════════════════════════════════════════╗
║                    OPENCLAW QUICK START                    ║
╚════════════════════════════════════════════════════════════╝

1. 🌐 ACCESS THE GATEWAY
   Open your browser to: http://192.168.122.100:18789

2. 🔑 AUTHENTICATE
   - Click "Control" in the left sidebar
   - Go to "Settings"
   - Paste this Gateway Token:
   
   54a80e7033ddbe58d1caefbfff670d04310dea6885c2da3d321454da14f333c0
   
   - Save settings

3. 💬 START CHATTING
   - Go to the "Chat" tab
   - You should see "Connected to gateway"
   - Start sending commands!

4. 📚 READ THE DOCS
   Full guide: OPENCLAW_GUIDE.md

Press Enter to continue...""")
        input()

    def show_config(self, stdscr):
        """Show current configuration"""
        curses.endwin()
        os.system("clear")
        print("╔════════════════════════════════════════════════════════════╗")
        print("║                CURRENT CONFIGURATION                       ║")
        print("╚════════════════════════════════════════════════════════════╝")
        print()
        print(json.dumps(self.config, indent=2))
        print()
        print("Config file:", self.config_path)
        print()
        input("Press Enter to continue...")

    def show_status(self, stdscr):
        """Show OpenClaw status"""
        curses.endwin()
        os.system("clear")
        print("╔════════════════════════════════════════════════════════════╗")
        print("║                   OPENCLAW STATUS                          ║")
        print("╚════════════════════════════════════════════════════════════╝")
        print()

        # Check docker containers
        result = subprocess.run(
            [
                "docker",
                "ps",
                "--filter",
                "name=openclaw",
                "--format",
                "table {{.Names}}\t{{.Status}}",
            ],
            capture_output=True,
            text=True,
        )
        print("🐳 Docker Containers:")
        print(result.stdout if result.stdout else "No containers running")
        print()

        # Check ports
        result = subprocess.run(["ss", "-tlnp"], capture_output=True, text=True)
        print("🌐 Network Ports:")
        for line in result.stdout.split("\n"):
            if "1878" in line:
                print(line)
        print()

        # Gateway URL
        print("🔗 Gateway URL: http://192.168.122.100:18789")
        print()
        input("Press Enter to continue...")

    def edit_gateway_mode(self, stdscr):
        """Edit gateway mode"""
        curses.endwin()
        os.system("clear")
        print("╔════════════════════════════════════════════════════════════╗")
        print("║                 GATEWAY MODE                               ║")
        print("╚════════════════════════════════════════════════════════════╝")
        print()
        print("Current mode:", self.config.get("gateway", {}).get("mode", "local"))
        print()
        print("1. local - Run locally (recommended)")
        print("2. remote - Connect to remote gateway")
        print()
        choice = input("Select mode (1-2): ").strip()

        if choice == "1":
            self.config.setdefault("gateway", {})["mode"] = "local"
        elif choice == "2":
            self.config.setdefault("gateway", {})["mode"] = "remote"

        self.message = f"Gateway mode set to: {self.config['gateway']['mode']}"

    def edit_gateway_port(self, stdscr):
        """Edit gateway port"""
        curses.endwin()
        os.system("clear")
        print("╔════════════════════════════════════════════════════════════╗")
        print("║                 GATEWAY PORT                               ║")
        print("╚════════════════════════════════════════════════════════════╝")
        print()
        current = self.config.get("gateway", {}).get("port", 18789)
        print(f"Current port: {current}")
        print()

        new_port = input("Enter new port (or press Enter to keep current): ").strip()
        if new_port.isdigit():
            self.config.setdefault("gateway", {})["port"] = int(new_port)
            self.message = f"Gateway port set to: {new_port}"

    def toggle_discord(self):
        """Toggle Discord enabled"""
        current = (
            self.config.get("channels", {}).get("discord", {}).get("enabled", False)
        )
        self.config.setdefault("channels", {}).setdefault("discord", {})[
            "enabled"
        ] = not current
        status = "enabled" if not current else "disabled"
        self.message = f"Discord integration {status}"

    def edit_discord_token(self, stdscr):
        """Edit Discord token"""
        curses.endwin()
        os.system("clear")
        print("╔════════════════════════════════════════════════════════════╗")
        print("║               DISCORD BOT TOKEN                            ║")
        print("╚════════════════════════════════════════════════════════════╝")
        print()
        print("Enter your Discord bot token.")
        print("Get one at: https://discord.com/developers/applications")
        print()

        token = input("Token: ").strip()
        if token:
            self.config.setdefault("channels", {}).setdefault("discord", {})[
                "token"
            ] = token
            self.message = "Discord token saved"

    def edit_max_concurrent(self, stdscr):
        """Edit max concurrent agents"""
        curses.endwin()
        os.system("clear")
        print("╔════════════════════════════════════════════════════════════╗")
        print("║            MAX CONCURRENT AGENTS                           ║")
        print("╚════════════════════════════════════════════════════════════╝")
        print()
        current = (
            self.config.get("agents", {}).get("defaults", {}).get("maxConcurrent", 4)
        )
        print(f"Current: {current}")
        print()

        new_val = input("Enter max concurrent agents: ").strip()
        if new_val.isdigit():
            self.config.setdefault("agents", {}).setdefault("defaults", {})[
                "maxConcurrent"
            ] = int(new_val)
            self.message = f"Max concurrent agents set to: {new_val}"

    def edit_subagent_max(self, stdscr):
        """Edit max subagents"""
        curses.endwin()
        os.system("clear")
        print("╔════════════════════════════════════════════════════════════╗")
        print("║                 MAX SUBAGENTS                              ║")
        print("╚════════════════════════════════════════════════════════════╝")
        print()
        current = (
            self.config.get("agents", {})
            .get("defaults", {})
            .get("subagents", {})
            .get("maxConcurrent", 8)
        )
        print(f"Current: {current}")
        print()

        new_val = input("Enter max subagents: ").strip()
        if new_val.isdigit():
            self.config.setdefault("agents", {}).setdefault("defaults", {}).setdefault(
                "subagents", {}
            )["maxConcurrent"] = int(new_val)
            self.message = f"Max subagents set to: {new_val}"

    def restart_openclaw(self):
        """Restart OpenClaw containers"""
        try:
            subprocess.run(
                [
                    "docker",
                    "compose",
                    "-f",
                    str(Path.home() / "openclaw" / "docker-compose.yml"),
                    "restart",
                ],
                capture_output=True,
                check=True,
            )
        except Exception as e:
            self.message = f"Error restarting: {e}"

    def run(self, stdscr):
        """Main TUI loop"""
        # Setup colors
        curses.start_color()
        curses.init_pair(1, curses.COLOR_GREEN, curses.COLOR_BLACK)
        curses.init_pair(2, curses.COLOR_YELLOW, curses.COLOR_BLACK)
        curses.init_pair(3, curses.COLOR_CYAN, curses.COLOR_BLACK)
        curses.init_pair(4, curses.COLOR_BLUE, curses.COLOR_BLACK)

        # Hide cursor
        curses.curs_set(0)

        while True:
            stdscr.clear()
            self.draw_header(stdscr)
            self.draw_menu(stdscr)
            stdscr.refresh()

            key = stdscr.getch()
            if not self.handle_input(stdscr, key):
                break


def main():
    """Entry point"""
    try:
        app = OpenClawTUI()
        curses.wrapper(app.run)
    except KeyboardInterrupt:
        print("\n\nGoodbye! 👋")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
