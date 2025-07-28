#!/usr/bin/env python3
"""
Enhanced TUI Interface for OWASP ZAP DAST Scanner
Intuitive terminal user interface for security testing configuration
"""

import os
import sys
import yaml
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, asdict
from datetime import datetime

# Rich TUI components
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.columns import Columns
from rich.text import Text
from rich.prompt import Prompt, Confirm, IntPrompt
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
from rich.layout import Layout
from rich.live import Live
from rich.tree import Tree
from rich.align import Align
from rich.rule import Rule
from rich import box
from rich.markup import escape
from rich.padding import Padding

# Import our scanner
try:
    from zap_scanner import ZAPScanner, ScanConfig, ScanResults
except ImportError:
    print("Error: zap_scanner.py not found. Ensure it's in the same directory.")
    sys.exit(1)

class DASTInterface:
    """Enhanced TUI interface for DAST scanner"""
    
    def __init__(self):
        self.console = Console()
        self.config = None
        self.scanner = None
        self.current_scan_results = None
        
        # Menu state
        self.main_menu_options = [
            "🚀 Quick Scan",
            "⚙️  Custom Scan Configuration", 
            "📊 View Previous Results",
            "🐳 Docker ZAP Management",
            "📋 Scan Profiles",
            "📖 OWASP Top 10 Guide",
            "⚡ Advanced Options",
            "❌ Exit"
        ]
        
        # Predefined scan profiles
        self.scan_profiles = {
            "Quick Security Check": {
                "description": "Fast scan focusing on critical vulnerabilities",
                "spider_depth": 2,
                "spider_max_children": 5,
                "ajax_spider_enabled": False,
                "timeout": 120
            },
            "Comprehensive Audit": {
                "description": "Thorough scan covering all OWASP Top 10",
                "spider_depth": 8,
                "spider_max_children": 15,
                "ajax_spider_enabled": True,
                "timeout": 600
            },
            "API Security Test": {
                "description": "Focused on REST API endpoints and authentication",
                "spider_depth": 3,
                "spider_max_children": 10,
                "ajax_spider_enabled": False,
                "timeout": 300
            },
            "Authentication Bypass": {
                "description": "Specialized scan for auth vulnerabilities",
                "spider_depth": 5,
                "spider_max_children": 8,
                "ajax_spider_enabled": True,
                "timeout": 240
            }
        }

    def display_welcome_banner(self):
        """Display welcome banner with ASCII art"""
        banner_text = """
╔══════════════════════════════════════════════════════════════════════════════════════╗
║                             🛡️  JARVIS DAST SECURITY SUITE 🛡️                        ║
║                                                                                      ║
║                          Advanced Web Application Security Testing                   ║
║                              Powered by OWASP ZAP & Python                         ║
║                                                                                      ║
║                    🔍 Automated Vulnerability Detection                              ║
║                    📊 OWASP Top 10 Coverage Analysis                                 ║
║                    🎯 Intelligent Scanning Algorithms                               ║
║                    📈 Professional Security Reports                                 ║
╚══════════════════════════════════════════════════════════════════════════════════════╝
        """
        
        self.console.print(Panel(
            banner_text,
            style="bold blue",
            box=box.DOUBLE,
            padding=(1, 2)
        ))
        
        # System status check
        self.display_system_status()

    def display_system_status(self):
        """Display current system status"""
        status_items = []
        
        # Check ZAP availability
        try:
            import requests
            response = requests.get("http://127.0.0.1:8080", timeout=2)
            zap_status = "[green]✅ Running[/green]"
        except:
            zap_status = "[red]❌ Not Running[/red]"
        
        # Check target availability  
        try:
            import requests
            response = requests.get("http://localhost:9000", timeout=5)
            target_status = "[green]✅ Accessible[/green]"
        except:
            target_status = "[yellow]⚠️  Not Accessible[/yellow]"
        
        # Check Docker
        try:
            import subprocess
            result = subprocess.run(["docker", "--version"], capture_output=True, timeout=5)
            docker_status = "[green]✅ Available[/green]" if result.returncode == 0 else "[red]❌ Not Available[/red]"
        except:
            docker_status = "[red]❌ Not Available[/red]"
        
        status_table = Table(show_header=False, box=None, padding=(0, 2))
        status_table.add_column("Component", style="bold")
        status_table.add_column("Status")
        
        status_table.add_row("OWASP ZAP Proxy", zap_status)
        status_table.add_row("Target Application", target_status)
        status_table.add_row("Docker Engine", docker_status)
        
        self.console.print(Panel(
            status_table,
            title="[bold yellow]🔧 System Status[/bold yellow]",
            border_style="yellow"
        ))

    def show_main_menu(self) -> str:
        """Display main menu and get user selection"""
        self.console.print("\n")
        
        menu_table = Table(show_header=False, box=box.ROUNDED, padding=(0, 2))
        menu_table.add_column("Option", style="bold cyan", width=40)
        menu_table.add_column("Description", style="dim")
        
        descriptions = [
            "Start immediate security scan with default settings",
            "Configure detailed scan parameters and options",  
            "Browse and analyze previous scan reports",
            "Manage ZAP container and service configuration",
            "Select from predefined scanning profiles",
            "Learn about OWASP Top 10 vulnerabilities",
            "Expert settings and advanced configuration",
            "Close the application"
        ]
        
        for i, (option, desc) in enumerate(zip(self.main_menu_options, descriptions)):
            menu_table.add_row(f"{i+1}. {option}", desc)
        
        self.console.print(Panel(
            menu_table,
            title="[bold green]📋 Main Menu[/bold green]",
            border_style="green"
        ))
        
        while True:
            try:
                choice = IntPrompt.ask(
                    "\n[bold cyan]Select an option[/bold cyan]",
                    choices=[str(i) for i in range(1, len(self.main_menu_options) + 1)],
                    show_choices=False
                )
                return self.main_menu_options[choice - 1]
            except KeyboardInterrupt:
                return "❌ Exit"

    def quick_scan_setup(self) -> ScanConfig:
        """Setup for quick scan with minimal configuration"""
        self.console.print(Panel(
            "[bold green]🚀 Quick Security Scan Setup[/bold green]\n\n"
            "This will perform a rapid security assessment using default settings.\n"
            "Perfect for initial vulnerability detection and CI/CD pipelines.",
            border_style="green"
        ))
        
        # Basic target configuration
        target_url = Prompt.ask(
            "[cyan]Target URL[/cyan]",
            default="http://localhost:9000"
        )
        
        # Optional authentication
        use_auth = Confirm.ask("[cyan]Include authentication testing?[/cyan]", default=False)
        
        auth_username = ""
        auth_password = ""
        if use_auth:
            auth_username = Prompt.ask("[cyan]Username[/cyan]")
            auth_password = Prompt.ask("[cyan]Password[/cyan]", password=True)
        
        return ScanConfig(
            target_url=target_url,
            spider_depth=3,
            spider_max_children=8,
            ajax_spider_enabled=True,
            auth_username=auth_username,
            auth_password=auth_password,
            timeout=180,
            context_name="QuickScan"
        )

    def custom_scan_configuration(self) -> ScanConfig:
        """Detailed custom scan configuration"""
        self.console.print(Panel(
            "[bold yellow]⚙️ Custom Scan Configuration[/bold yellow]\n\n"
            "Configure detailed parameters for comprehensive security testing.",
            border_style="yellow"
        ))
        
        # Target configuration
        self.console.print("\n[bold blue]🎯 Target Configuration[/bold blue]")
        target_url = Prompt.ask("[cyan]Primary target URL[/cyan]", default="http://localhost:9000")
        backend_url = Prompt.ask("[cyan]Backend API URL[/cyan]", default="http://localhost:8000")
        
        # Spider configuration
        self.console.print("\n[bold blue]🕷️ Spider Configuration[/bold blue]")
        spider_depth = IntPrompt.ask("[cyan]Spider crawl depth[/cyan]", default=5, choices=["1", "2", "3", "4", "5", "6", "7", "8", "9", "10"])
        spider_max_children = IntPrompt.ask("[cyan]Max pages per directory[/cyan]", default=10)
        ajax_spider_enabled = Confirm.ask("[cyan]Enable AJAX spider for modern web apps?[/cyan]", default=True)
        
        # Authentication setup
        self.console.print("\n[bold blue]🔐 Authentication Configuration[/bold blue]")
        use_auth = Confirm.ask("[cyan]Configure authentication?[/cyan]", default=False)
        
        auth_username = ""
        auth_password = ""
        if use_auth:
            auth_username = Prompt.ask("[cyan]Username[/cyan]")
            auth_password = Prompt.ask("[cyan]Password[/cyan]", password=True)
        
        # Scan policy
        self.console.print("\n[bold blue]🎯 Scan Policy[/bold blue]")
        policies = ["Default Policy", "Full Policy", "Light Policy", "API Policy"]
        active_scan_policy = Prompt.ask(
            "[cyan]Active scan policy[/cyan]",
            choices=policies,
            default="Default Policy"
        )
        
        # Timeout configuration
        timeout = IntPrompt.ask("[cyan]Scan timeout (seconds)[/cyan]", default=300)
        
        # Output configuration
        self.console.print("\n[bold blue]📄 Output Configuration[/bold blue]")
        output_dir = Prompt.ask("[cyan]Output directory[/cyan]", default="./reports")
        
        format_choices = ["html", "json", "xml"]
        selected_formats = []
        
        for fmt in format_choices:
            if Confirm.ask(f"[cyan]Generate {fmt.upper()} report?[/cyan]", default=True):
                selected_formats.append(fmt)
        
        return ScanConfig(
            target_url=target_url,
            backend_url=backend_url,
            spider_depth=spider_depth,
            spider_max_children=spider_max_children,
            ajax_spider_enabled=ajax_spider_enabled,
            active_scan_policy=active_scan_policy,
            auth_username=auth_username,
            auth_password=auth_password,
            timeout=timeout,
            output_dir=output_dir,
            report_formats=selected_formats
        )

    def display_scan_profiles(self) -> Optional[ScanConfig]:
        """Display and select from predefined scan profiles"""
        self.console.print(Panel(
            "[bold magenta]📋 Scan Profiles[/bold magenta]\n\n"
            "Choose from optimized scanning configurations for different use cases.",
            border_style="magenta"
        ))
        
        # Display profiles table
        profiles_table = Table(box=box.ROUNDED)
        profiles_table.add_column("Profile", style="bold")
        profiles_table.add_column("Description", style="dim")
        profiles_table.add_column("Duration", justify="center")
        profiles_table.add_column("Depth", justify="center")
        
        profile_names = list(self.scan_profiles.keys())
        durations = ["~2 mins", "~10 mins", "~5 mins", "~4 mins"]
        
        for i, (name, config) in enumerate(self.scan_profiles.items()):
            profiles_table.add_row(
                f"{i+1}. {name}",
                config["description"],
                durations[i],
                str(config["spider_depth"])
            )
        
        self.console.print(profiles_table)
        
        # Profile selection
        choice = IntPrompt.ask(
            "\n[cyan]Select a profile (0 to return)[/cyan]",
            choices=[str(i) for i in range(0, len(profile_names) + 1)]
        )
        
        if choice == 0:
            return None
        
        selected_profile = profile_names[choice - 1]
        profile_config = self.scan_profiles[selected_profile]
        
        # Get target URL
        target_url = Prompt.ask("[cyan]Target URL[/cyan]", default="http://localhost:9000")
        
        # Apply profile settings
        config = ScanConfig(
            target_url=target_url,
            spider_depth=profile_config["spider_depth"],
            spider_max_children=profile_config["spider_max_children"],
            ajax_spider_enabled=profile_config["ajax_spider_enabled"],
            timeout=profile_config["timeout"],
            context_name=selected_profile.replace(" ", "")
        )
        
        return config

    def view_previous_results(self):
        """View and analyze previous scan results"""
        self.console.print(Panel(
            "[bold cyan]📊 Previous Scan Results[/bold cyan]",
            border_style="cyan"
        ))
        
        reports_dir = Path("./reports")
        if not reports_dir.exists():
            self.console.print("[yellow]No previous scans found. Run a scan first![/yellow]")
            return
        
        # List available reports
        scan_dirs = [d for d in reports_dir.iterdir() if d.is_dir()]
        
        if not scan_dirs:
            self.console.print("[yellow]No scan reports found.[/yellow]")
            return
        
        # Display available scans
        scans_table = Table(box=box.ROUNDED)
        scans_table.add_column("Scan ID", style="bold")
        scans_table.add_column("Date", style="dim")
        scans_table.add_column("Reports Available")
        
        for scan_dir in sorted(scan_dirs, reverse=True):
            # Get available report files
            reports = []
            if (scan_dir / "security_report.html").exists():
                reports.append("HTML")
            if (scan_dir / "security_report.json").exists():
                reports.append("JSON")
            if (scan_dir / "security_report.xml").exists():
                reports.append("XML")
            
            # Parse date from scan ID
            try:
                date_part = scan_dir.name.split("_")[-2:]
                date_str = f"{date_part[0]} {date_part[1]}"
                formatted_date = datetime.strptime(date_str, "%Y%m%d %H%M%S").strftime("%Y-%m-%d %H:%M")
            except:
                formatted_date = "Unknown"
            
            scans_table.add_row(
                scan_dir.name,
                formatted_date,
                ", ".join(reports) if reports else "None"
            )
        
        self.console.print(scans_table)
        
        # Allow user to select and view a report
        if Confirm.ask("\n[cyan]View a specific report?[/cyan]"):
            scan_choice = Prompt.ask("[cyan]Enter scan ID[/cyan]")
            self.display_scan_summary(reports_dir / scan_choice)

    def display_scan_summary(self, scan_dir: Path):
        """Display summary of a specific scan"""
        json_report = scan_dir / "security_report.json"
        
        if not json_report.exists():
            self.console.print("[red]JSON report not found for this scan.[/red]")
            return
        
        try:
            with open(json_report) as f:
                scan_data = json.load(f)
            
            # Display summary
            summary_table = Table(title=f"📊 Scan Summary: {scan_dir.name}", box=box.ROUNDED)
            summary_table.add_column("Metric", style="bold")
            summary_table.add_column("Value")
            
            summary_table.add_row("Target URL", scan_data.get("target_url", "Unknown"))
            summary_table.add_row("Scan Duration", f"{scan_data.get('duration', 0):.1f} seconds")
            summary_table.add_row("URLs Discovered", str(len(scan_data.get("spider_urls", []))))
            summary_table.add_row("Total Vulnerabilities", str(len(scan_data.get("vulnerabilities", []))))
            
            self.console.print(summary_table)
            
            # Display vulnerability breakdown
            if "summary" in scan_data:
                vuln_table = Table(title="🚨 Vulnerability Breakdown", box=box.ROUNDED)
                vuln_table.add_column("Risk Level", style="bold")
                vuln_table.add_column("Count", justify="center")
                
                colors = {"High": "red", "Medium": "yellow", "Low": "blue", "Informational": "green"}
                
                for risk, count in scan_data["summary"].items():
                    vuln_table.add_row(
                        f"[{colors.get(risk, 'white')}]{risk}[/{colors.get(risk, 'white')}]",
                        str(count)
                    )
                
                self.console.print(vuln_table)
            
        except Exception as e:
            self.console.print(f"[red]Error reading scan report: {e}[/red]")

    def docker_zap_management(self):
        """Manage ZAP Docker container"""
        self.console.print(Panel(
            "[bold blue]🐳 Docker ZAP Management[/bold blue]\n\n"
            "Manage OWASP ZAP Docker container for automated scanning.",
            border_style="blue"
        ))
        
        docker_options = [
            "🚀 Start ZAP Container",
            "🛑 Stop ZAP Container", 
            "📊 Container Status",
            "🔄 Restart ZAP Container",
            "📋 View ZAP Logs",
            "⬅️  Back to Main Menu"
        ]
        
        for i, option in enumerate(docker_options, 1):
            self.console.print(f"{i}. {option}")
        
        choice = IntPrompt.ask(
            "\n[cyan]Select option[/cyan]",
            choices=[str(i) for i in range(1, len(docker_options) + 1)]
        )
        
        if choice == 1:
            self.start_zap_container()
        elif choice == 2:
            self.stop_zap_container()
        elif choice == 3:
            self.check_zap_status()
        elif choice == 4:
            self.restart_zap_container()
        elif choice == 5:
            self.view_zap_logs()

    def start_zap_container(self):
        """Start ZAP Docker container"""
        self.console.print("[yellow]🚀 Starting ZAP container...[/yellow]")
        
        try:
            import subprocess
            
            # ZAP Docker command
            cmd = [
                "docker", "run", "-d",
                "--name", "owasp-zap",
                "-p", "8080:8080",
                "-p", "8090:8090",  # ZAP daemon port
                "owasp/zap2docker-stable",
                "zap.sh", "-daemon",
                "-host", "0.0.0.0",
                "-port", "8080",
                "-config", "api.disablekey=true"
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0:
                self.console.print("[green]✅ ZAP container started successfully![/green]")
                self.console.print("Container is starting up, please wait 10-15 seconds...")
            else:
                self.console.print(f"[red]❌ Failed to start ZAP container: {result.stderr}[/red]")
                
        except Exception as e:
            self.console.print(f"[red]❌ Error starting ZAP container: {e}[/red]")

    def stop_zap_container(self):
        """Stop ZAP Docker container"""
        self.console.print("[yellow]🛑 Stopping ZAP container...[/yellow]")
        
        try:
            import subprocess
            
            # Stop and remove container
            subprocess.run(["docker", "stop", "owasp-zap"], capture_output=True, timeout=10)
            subprocess.run(["docker", "rm", "owasp-zap"], capture_output=True, timeout=10)
            
            self.console.print("[green]✅ ZAP container stopped successfully![/green]")
            
        except Exception as e:
            self.console.print(f"[red]❌ Error stopping ZAP container: {e}[/red]")

    def check_zap_status(self):
        """Check ZAP container status"""
        try:
            import subprocess
            
            result = subprocess.run(
                ["docker", "ps", "--filter", "name=owasp-zap", "--format", "table {{.Names}}\t{{.Status}}\t{{.Ports}}"],
                capture_output=True, text=True, timeout=10
            )
            
            if "owasp-zap" in result.stdout:
                self.console.print("[green]✅ ZAP container is running[/green]")
                self.console.print(result.stdout)
            else:
                self.console.print("[yellow]⚠️  ZAP container is not running[/yellow]")
                
        except Exception as e:
            self.console.print(f"[red]❌ Error checking ZAP status: {e}[/red]")

    def restart_zap_container(self):
        """Restart ZAP container"""
        self.stop_zap_container()
        time.sleep(2)
        self.start_zap_container()

    def view_zap_logs(self):
        """View ZAP container logs"""
        try:
            import subprocess
            
            result = subprocess.run(
                ["docker", "logs", "--tail", "50", "owasp-zap"],
                capture_output=True, text=True, timeout=10
            )
            
            if result.returncode == 0:
                self.console.print(Panel(
                    result.stdout,
                    title="[bold yellow]📋 ZAP Container Logs[/bold yellow]",
                    border_style="yellow"
                ))
            else:
                self.console.print("[red]❌ Could not retrieve ZAP logs[/red]")
                
        except Exception as e:
            self.console.print(f"[red]❌ Error retrieving ZAP logs: {e}[/red]")

    def show_owasp_guide(self):
        """Display OWASP Top 10 guide"""
        self.console.print(Panel(
            "[bold red]📖 OWASP Top 10 2021 Security Guide[/bold red]",
            border_style="red"
        ))
        
        owasp_info = {
            "A01:2021 – Broken Access Control": {
                "description": "Restrictions on authenticated users not properly enforced",
                "examples": ["Elevation of privilege", "Metadata manipulation", "CORS misconfiguration"],
                "detection": "Access control tests, authorization bypass attempts"
            },
            "A02:2021 – Cryptographic Failures": {
                "description": "Failures related to cryptography leading to data exposure",
                "examples": ["Transmitting data in clear text", "Using old cryptographic algorithms"],
                "detection": "SSL/TLS analysis, cipher suite evaluation"
            },
            "A03:2021 – Injection": {
                "description": "User-supplied data not validated, filtered, or sanitized",
                "examples": ["SQL injection", "Cross-site scripting", "Command injection"],
                "detection": "Input validation tests, payload injection attempts"
            }
        }
        
        for category, info in owasp_info.items():
            category_panel = Panel(
                f"[bold]{info['description']}[/bold]\n\n"
                f"[yellow]Examples:[/yellow] {', '.join(info['examples'])}\n\n"
                f"[green]Detection:[/green] {info['detection']}",
                title=f"[red]{category}[/red]",
                border_style="red"
            )
            self.console.print(category_panel)
            
        self.console.print("\n[dim]Press Enter to continue...[/dim]")
        input()

    def run_scan_with_progress(self, config: ScanConfig):
        """Run scan with enhanced progress display"""
        self.console.print(Panel(
            f"[bold green]🚀 Starting Security Scan[/bold green]\n\n"
            f"[yellow]Target:[/yellow] {config.target_url}\n"
            f"[yellow]Context:[/yellow] {config.context_name}\n"
            f"[yellow]Spider Depth:[/yellow] {config.spider_depth}\n"
            f"[yellow]AJAX Spider:[/yellow] {'Enabled' if config.ajax_spider_enabled else 'Disabled'}",
            border_style="green"
        ))
        
        # Initialize scanner
        scanner = ZAPScanner(config)
        
        # Check prerequisites
        if not scanner.check_prerequisites():
            self.console.print("[red]❌ Prerequisites check failed. Please ensure ZAP is running.[/red]")
            return None
        
        # Initialize ZAP connection
        if not scanner.initialize_zap():
            self.console.print("[red]❌ Failed to connect to ZAP API.[/red]")
            return None
        
        try:
            # Run scan with progress
            results = scanner.run_full_scan()
            
            # Display results
            scanner.display_results_table(results)
            
            # Generate reports
            scanner.generate_reports(results)
            
            self.current_scan_results = results
            return results
            
        except KeyboardInterrupt:
            self.console.print("\n[yellow]⚠️  Scan interrupted by user[/yellow]")
            return None
        except Exception as e:
            self.console.print(f"\n[red]❌ Scan failed: {e}[/red]")
            return None

    def main_loop(self):
        """Main application loop"""
        self.display_welcome_banner()
        
        while True:
            try:
                choice = self.show_main_menu()
                
                if choice == "❌ Exit":
                    self.console.print("\n[bold green]👋 Thank you for using JARVIS DAST Scanner![/bold green]")
                    break
                    
                elif choice == "🚀 Quick Scan":
                    config = self.quick_scan_setup()
                    if config:
                        self.run_scan_with_progress(config)
                        
                elif choice == "⚙️  Custom Scan Configuration":
                    config = self.custom_scan_configuration()
                    if config:
                        self.run_scan_with_progress(config)
                        
                elif choice == "📊 View Previous Results":
                    self.view_previous_results()
                    
                elif choice == "🐳 Docker ZAP Management":
                    self.docker_zap_management()
                    
                elif choice == "📋 Scan Profiles":
                    config = self.display_scan_profiles()
                    if config:
                        self.run_scan_with_progress(config)
                        
                elif choice == "📖 OWASP Top 10 Guide":
                    self.show_owasp_guide()
                    
                elif choice == "⚡ Advanced Options":
                    self.console.print("[yellow]Advanced options coming in future updates![/yellow]")
                
                # Pause before returning to menu
                if choice != "❌ Exit":
                    self.console.print("\n[dim]Press Enter to return to main menu...[/dim]")
                    input()
                    
            except KeyboardInterrupt:
                self.console.print("\n\n[bold green]👋 Goodbye![/bold green]")
                break
            except Exception as e:
                self.console.print(f"\n[red]❌ Unexpected error: {e}[/red]")
                self.console.print("[dim]Press Enter to continue...[/dim]")
                input()

def main():
    """Entry point"""
    try:
        interface = DASTInterface()
        interface.main_loop()
    except KeyboardInterrupt:
        print("\n\nExiting...")
        sys.exit(0)

if __name__ == "__main__":
    main()