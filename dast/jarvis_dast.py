#!/usr/bin/env python3
"""
JARVIS DAST - Unified Security Testing Tool
Single TUI application for comprehensive web application security testing
"""

import os
import sys
import json
import yaml
import time
import csv
import subprocess
import requests
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, asdict
import argparse
import logging

# Rich TUI framework
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.columns import Columns
from rich.text import Text
from rich.prompt import Prompt, Confirm, IntPrompt
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.layout import Layout
from rich.live import Live
from rich.tree import Tree
from rich.align import Align
from rich.rule import Rule
from rich import box
from rich.markup import escape
from rich.padding import Padding

# ZAP Python API
try:
    from zapv2 import ZAPv2
    ZAP_AVAILABLE = True
except ImportError:
    ZAP_AVAILABLE = False

# Optional visualization libraries
try:
    import matplotlib.pyplot as plt
    import seaborn as sns
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False

@dataclass
class ScanConfig:
    """Configuration for ZAP scan"""
    target_url: str = "http://localhost:9000"
    backend_url: str = "http://localhost:8000"
    zap_proxy_host: str = "127.0.0.1"
    zap_proxy_port: int = 8080
    api_key: Optional[str] = None
    spider_depth: int = 5
    spider_max_children: int = 10
    ajax_spider_enabled: bool = True
    active_scan_policy: str = "Default Policy"
    auth_username: str = ""
    auth_password: str = ""
    session_management: bool = True
    context_name: str = "JarvisApp"
    output_dir: str = "./reports"
    report_formats: List[str] = None
    timeout: int = 300
    
    def __post_init__(self):
        if self.report_formats is None:
            self.report_formats = ["html", "json", "xml"]

@dataclass 
class VulnerabilityResult:
    """Single vulnerability result"""
    name: str
    risk: str
    confidence: str
    url: str
    param: str
    attack: str
    evidence: str
    description: str
    solution: str
    reference: str
    cwe_id: str
    wasc_id: str
    source_id: str

@dataclass
class ScanResults:
    """Complete scan results"""
    scan_id: str
    timestamp: str
    target_url: str
    duration: float
    vulnerabilities: List[VulnerabilityResult]
    spider_urls: List[str]
    ajax_spider_urls: List[str]
    summary: Dict[str, int]
    owasp_top10_coverage: Dict[str, List[VulnerabilityResult]]

class JarvisDAST:
    """Unified DAST Security Testing Tool"""
    
    def __init__(self):
        self.console = Console()
        self.zap = None
        self.current_scan_results = None
        self.config = None
        
        # OWASP Top 10 2021 mapping
        self.owasp_top10_mapping = {
            "A01:2021 – Broken Access Control": [
                "Access Control Issue", "Directory Browsing", "Path Traversal",
                "Remote File Inclusion", "Cross Domain Misconfiguration"
            ],
            "A02:2021 – Cryptographic Failures": [
                "Weak Authentication Method", "Password Autocomplete",
                "Weak HTTP Authentication", "Cookie Security"
            ],
            "A03:2021 – Injection": [
                "SQL Injection", "Cross Site Scripting", "LDAP Injection",
                "Command Injection", "Code Injection", "XPath Injection"
            ],
            "A04:2021 – Insecure Design": [
                "Insufficient Anti-automation", "Missing Rate Limiting"
            ],
            "A05:2021 – Security Misconfiguration": [
                "Application Error Disclosure", "Server Leaks Information",
                "X-Frame-Options Header Not Set", "X-Content-Type-Options Header Missing",
                "Content Security Policy (CSP) Header Not Set"
            ],
            "A06:2021 – Vulnerable and Outdated Components": [
                "Vulnerable JS Library", "Outdated Component"
            ],
            "A07:2021 – Identification and Authentication Failures": [
                "Session Fixation", "Session ID in URL Rewrite",
                "Weak Authentication Method"
            ],
            "A08:2021 – Software and Data Integrity Failures": [
                "Sub Resource Integrity Attribute Missing"
            ],
            "A09:2021 – Security Logging and Monitoring Failures": [
                "Information Disclosure - Debug Error Messages"
            ],
            "A10:2021 – Server-Side Request Forgery": [
                "Server Side Request Forgery"
            ]
        }
        
        # Scan profiles
        self.scan_profiles = {
            "🚀 Quick Security Check": {
                "description": "Fast scan focusing on critical vulnerabilities (2-3 mins)",
                "spider_depth": 2,
                "spider_max_children": 5,
                "ajax_spider_enabled": False,
                "timeout": 120
            },
            "🔍 Comprehensive Audit": {
                "description": "Thorough scan covering all OWASP Top 10 (8-10 mins)",
                "spider_depth": 8,
                "spider_max_children": 15,
                "ajax_spider_enabled": True,
                "timeout": 600
            },
            "🔗 API Security Test": {
                "description": "Focused on REST API endpoints and authentication (4-5 mins)",
                "spider_depth": 3,
                "spider_max_children": 10,
                "ajax_spider_enabled": False,
                "timeout": 300
            },
            "🔐 Authentication Bypass": {
                "description": "Specialized scan for auth vulnerabilities (3-4 mins)",
                "spider_depth": 5,
                "spider_max_children": 8,
                "ajax_spider_enabled": True,
                "timeout": 240
            }
        }
        
        # Menu options
        self.main_menu_options = [
            "🚀 Quick Scan",
            "⚙️  Custom Configuration", 
            "📋 Scan Profiles",
            "🐳 ZAP Management",
            "📊 View Results",
            "📖 Security Guide",
            "⚡ Settings",
            "❌ Exit"
        ]

    def display_banner(self):
        """Display application banner"""
        banner = """
╔══════════════════════════════════════════════════════════════════════════════════════╗
║                             🛡️  JARVIS DAST SECURITY TOOL 🛡️                         ║
║                                                                                      ║
║                          Comprehensive Web Application Security Testing              ║
║                              Powered by OWASP ZAP & Python                         ║
║                                                                                      ║
║                    🔍 Automated Vulnerability Detection                              ║
║                    📊 OWASP Top 10 Coverage Analysis                                 ║
║                    🎯 Intelligent Scanning Algorithms                               ║
║                    📈 Professional Security Reports                                 ║
╚══════════════════════════════════════════════════════════════════════════════════════╝
        """
        
        self.console.print(Panel(
            banner,
            style="bold blue",
            box=box.DOUBLE,
            padding=(1, 2)
        ))
        
        # Display system status
        self.display_system_status()

    def display_system_status(self):
        """Display current system and service status"""
        status_items = []
        
        # Check ZAP availability
        try:
            response = requests.get(f"http://{self.config.zap_proxy_host if self.config else '127.0.0.1'}:8080", timeout=2)
            zap_status = "[green]✅ Running[/green]"
        except:
            zap_status = "[red]❌ Not Running[/red]"
        
        # Check target availability  
        target_url = self.config.target_url if self.config else "http://localhost:9000"
        try:
            response = requests.get(target_url, timeout=5)
            target_status = "[green]✅ Accessible[/green]"
        except:
            target_status = "[yellow]⚠️  Not Accessible[/yellow]"
        
        # Check Docker
        try:
            result = subprocess.run(["docker", "--version"], capture_output=True, timeout=5)
            docker_status = "[green]✅ Available[/green]" if result.returncode == 0 else "[red]❌ Not Available[/red]"
        except:
            docker_status = "[red]❌ Not Available[/red]"
        
        # Check ZAP Python API
        zap_api_status = "[green]✅ Available[/green]" if ZAP_AVAILABLE else "[red]❌ Not Installed[/red]"
        
        status_table = Table(show_header=False, box=None, padding=(0, 2))
        status_table.add_column("Component", style="bold", width=25)
        status_table.add_column("Status")
        
        status_table.add_row("OWASP ZAP Proxy", zap_status)
        status_table.add_row("Target Application", target_status)
        status_table.add_row("Docker Engine", docker_status)
        status_table.add_row("ZAP Python API", zap_api_status)
        
        self.console.print(Panel(
            status_table,
            title="[bold yellow]🔧 System Status[/bold yellow]",
            border_style="yellow"
        ))

    def show_main_menu(self) -> str:
        """Display main menu and get user selection"""
        self.console.print("\n")
        
        menu_table = Table(show_header=False, box=box.ROUNDED, padding=(0, 2))
        menu_table.add_column("Option", style="bold cyan", width=30)
        menu_table.add_column("Description", style="dim")
        
        descriptions = [
            "Start immediate security scan with default settings",
            "Configure detailed scan parameters and options",  
            "Select from predefined scanning profiles",
            "Manage ZAP container and service configuration",
            "Browse and analyze scan reports and results",
            "Learn about OWASP Top 10 vulnerabilities",
            "Application settings and preferences",
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
        
        format_choices = ["html", "json", "xml", "csv"]
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
        profiles_table.add_column("Profile", style="bold", width=25)
        profiles_table.add_column("Description", style="dim", width=50)
        profiles_table.add_column("Depth", justify="center", width=8)
        
        profile_names = list(self.scan_profiles.keys())
        
        for i, (name, config) in enumerate(self.scan_profiles.items()):
            profiles_table.add_row(
                f"{i+1}. {name}",
                config["description"],
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
            context_name=selected_profile.replace(" ", "").replace("🚀", "").replace("🔍", "").replace("🔗", "").replace("🔐", "").strip()
        )
        
        return config

    def zap_management(self):
        """Manage ZAP Docker container and services"""
        self.console.print(Panel(
            "[bold blue]🐳 ZAP Management[/bold blue]\n\n"
            "Manage OWASP ZAP Docker container and service configuration.",
            border_style="blue"
        ))
        
        docker_options = [
            "🚀 Start ZAP Container",
            "🛑 Stop ZAP Container", 
            "📊 Container Status",
            "🔄 Restart ZAP Container",
            "📋 View ZAP Logs",
            "🔧 ZAP Configuration",
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
        elif choice == 6:
            self.configure_zap()

    def start_zap_container(self):
        """Start ZAP Docker container"""
        self.console.print("[yellow]🚀 Starting ZAP container...[/yellow]")
        
        try:
            # Check if container already exists
            check_cmd = ["docker", "ps", "-a", "--filter", "name=jarvis-zap", "--format", "{{.Names}}"]
            result = subprocess.run(check_cmd, capture_output=True, text=True, timeout=10)
            
            if "jarvis-zap" in result.stdout:
                # Container exists, start it
                start_cmd = ["docker", "start", "jarvis-zap"]
                result = subprocess.run(start_cmd, capture_output=True, text=True, timeout=30)
                
                if result.returncode == 0:
                    self.console.print("[green]✅ ZAP container started successfully![/green]")
                else:
                    self.console.print(f"[red]❌ Failed to start existing container: {result.stderr}[/red]")
            else:
                # Create new container
                cmd = [
                    "docker", "run", "-d",
                    "--name", "jarvis-zap",
                    "-p", "8080:8080",
                    "-p", "8090:8090",
                    "owasp/zap2docker-stable",
                    "zap.sh", "-daemon",
                    "-host", "0.0.0.0",
                    "-port", "8080",
                    "-config", "api.disablekey=true"
                ]
                
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
                
                if result.returncode == 0:
                    self.console.print("[green]✅ ZAP container created and started successfully![/green]")
                    self.console.print("[yellow]⏳ Container is starting up, please wait 15-20 seconds...[/yellow]")
                else:
                    self.console.print(f"[red]❌ Failed to create ZAP container: {result.stderr}[/red]")
                
        except subprocess.TimeoutExpired:
            self.console.print("[red]❌ ZAP container startup timed out[/red]")
        except Exception as e:
            self.console.print(f"[red]❌ Error managing ZAP container: {e}[/red]")

    def stop_zap_container(self):
        """Stop ZAP Docker container"""
        self.console.print("[yellow]🛑 Stopping ZAP container...[/yellow]")
        
        try:
            result = subprocess.run(["docker", "stop", "jarvis-zap"], capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0:
                self.console.print("[green]✅ ZAP container stopped successfully![/green]")
            else:
                self.console.print("[yellow]⚠️  ZAP container may not be running[/yellow]")
                
        except Exception as e:
            self.console.print(f"[red]❌ Error stopping ZAP container: {e}[/red]")

    def check_zap_status(self):
        """Check ZAP container status"""
        try:
            # Check container status
            result = subprocess.run(
                ["docker", "ps", "--filter", "name=jarvis-zap", "--format", "table {{.Names}}\t{{.Status}}\t{{.Ports}}"],
                capture_output=True, text=True, timeout=10
            )
            
            if "jarvis-zap" in result.stdout:
                self.console.print("[green]✅ ZAP container is running[/green]")
                self.console.print(Panel(result.stdout, title="Container Status", border_style="green"))
            else:
                self.console.print("[yellow]⚠️  ZAP container is not running[/yellow]")
            
            # Check ZAP API accessibility
            try:
                response = requests.get("http://127.0.0.1:8080", timeout=5)
                self.console.print("[green]✅ ZAP API is accessible[/green]")
            except:
                self.console.print("[red]❌ ZAP API is not accessible[/red]")
                
        except Exception as e:
            self.console.print(f"[red]❌ Error checking ZAP status: {e}[/red]")

    def restart_zap_container(self):
        """Restart ZAP container"""
        self.stop_zap_container()
        time.sleep(3)
        self.start_zap_container()

    def view_zap_logs(self):
        """View ZAP container logs"""
        try:
            result = subprocess.run(
                ["docker", "logs", "--tail", "50", "jarvis-zap"],
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

    def configure_zap(self):
        """Configure ZAP settings"""
        self.console.print(Panel(
            "[bold cyan]🔧 ZAP Configuration[/bold cyan]\n\n"
            "Configure ZAP proxy and API settings.",
            border_style="cyan"
        ))
        
        current_config = self.config or ScanConfig()
        
        # ZAP proxy configuration
        zap_host = Prompt.ask("[cyan]ZAP proxy host[/cyan]", default=current_config.zap_proxy_host)
        zap_port = IntPrompt.ask("[cyan]ZAP proxy port[/cyan]", default=current_config.zap_proxy_port)
        
        # Update configuration
        if self.config:
            self.config.zap_proxy_host = zap_host
            self.config.zap_proxy_port = zap_port
        else:
            self.config = ScanConfig(zap_proxy_host=zap_host, zap_proxy_port=zap_port)
        
        self.console.print("[green]✅ ZAP configuration updated[/green]")

    def view_scan_results(self):
        """View and analyze previous scan results"""
        self.console.print(Panel(
            "[bold cyan]📊 Scan Results & Reports[/bold cyan]",
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
        scans_table.add_column("Scan ID", style="bold", width=30)
        scans_table.add_column("Date", style="dim", width=20)
        scans_table.add_column("Target", style="cyan", width=30)
        scans_table.add_column("Reports", width=15)
        
        for scan_dir in sorted(scan_dirs, reverse=True)[:10]:  # Show last 10 scans
            # Get available report files
            reports = []
            if (scan_dir / "security_report.html").exists():
                reports.append("HTML")
            if (scan_dir / "enhanced_security_report.json").exists():
                reports.append("JSON")
            if (scan_dir / "security_report.xml").exists():
                reports.append("XML")
            if (scan_dir / "vulnerabilities_report.csv").exists():
                reports.append("CSV")
            
            # Parse date from scan ID
            try:
                date_part = scan_dir.name.split("_")[-2:]
                if len(date_part) >= 2:
                    date_str = f"{date_part[0]} {date_part[1]}"
                    formatted_date = datetime.strptime(date_str, "%Y%m%d %H%M%S").strftime("%Y-%m-%d %H:%M")
                else:
                    formatted_date = "Unknown"
            except:
                formatted_date = "Unknown"
            
            # Get target from JSON report
            target_url = "Unknown"
            json_report = scan_dir / "enhanced_security_report.json"
            if json_report.exists():
                try:
                    with open(json_report) as f:
                        data = json.load(f)
                        target_url = data.get("scan_metadata", {}).get("target_url", "Unknown")[:28] + ("..." if len(data.get("scan_metadata", {}).get("target_url", "")) > 28 else "")
                except:
                    pass
            
            scans_table.add_row(
                scan_dir.name,
                formatted_date,
                target_url,
                ", ".join(reports) if reports else "None"
            )
        
        self.console.print(scans_table)
        
        # Allow user to select and view a report
        if scan_dirs and Confirm.ask("\n[cyan]View a specific report?[/cyan]"):
            scan_choice = Prompt.ask("[cyan]Enter scan ID[/cyan]")
            selected_scan = reports_dir / scan_choice
            
            if selected_scan.exists():
                self.display_scan_summary(selected_scan)
            else:
                self.console.print("[red]❌ Scan not found[/red]")

    def display_scan_summary(self, scan_dir: Path):
        """Display detailed summary of a specific scan"""
        json_report = scan_dir / "enhanced_security_report.json"
        
        if not json_report.exists():
            self.console.print("[red]❌ Detailed report not found for this scan[/red]")
            return
        
        try:
            with open(json_report) as f:
                scan_data = json.load(f)
            
            # Extract key information
            metadata = scan_data.get("scan_metadata", {})
            summary = scan_data.get("summary", {})
            risk_analysis = scan_data.get("risk_analysis", {})
            
            # Display scan overview
            overview_table = Table(title=f"📊 Scan Overview: {scan_dir.name}", box=box.ROUNDED)
            overview_table.add_column("Metric", style="bold", width=25)
            overview_table.add_column("Value", width=30)
            
            overview_table.add_row("Target URL", metadata.get("target_url", "Unknown"))
            overview_table.add_row("Scan Duration", f"{metadata.get('duration', 0):.1f} seconds")
            overview_table.add_row("URLs Discovered", str(summary.get("urls_tested", 0)))
            overview_table.add_row("Total Vulnerabilities", str(summary.get("total_vulnerabilities", 0)))
            overview_table.add_row("Overall Risk Level", risk_analysis.get("overall_risk", "Unknown"))
            
            self.console.print(overview_table)
            
            # Display vulnerability breakdown
            if "risk_distribution" in summary:
                vuln_table = Table(title="🚨 Vulnerability Breakdown", box=box.ROUNDED)
                vuln_table.add_column("Risk Level", style="bold")
                vuln_table.add_column("Count", justify="center")
                vuln_table.add_column("Percentage", justify="center")
                
                colors = {"High": "red", "Medium": "yellow", "Low": "blue", "Informational": "green"}
                risk_dist = summary.get("risk_distribution", {})
                total = sum(risk_dist.values()) if risk_dist.values() else 1
                
                for risk, count in risk_dist.items():
                    percentage = f"{(count/total*100):.1f}%" if total > 0 else "0%"
                    vuln_table.add_row(
                        f"[{colors.get(risk, 'white')}]{risk}[/{colors.get(risk, 'white')}]",
                        str(count),
                        percentage
                    )
                
                self.console.print(vuln_table)
            
            # Display OWASP Top 10 analysis
            if "owasp_top10_analysis" in scan_data:
                owasp_table = Table(title="🛡️ OWASP Top 10 Analysis", box=box.ROUNDED)
                owasp_table.add_column("Category", style="bold", width=35)
                owasp_table.add_column("Issues Found", justify="center")
                owasp_table.add_column("Status")
                
                for category, analysis in scan_data["owasp_top10_analysis"].items():
                    count = analysis.get("vulnerability_count", 0)
                    status = "✅ Tested" if count > 0 else "🔍 No Issues"
                    color = "red" if count > 0 else "green"
                    
                    # Shorten category name
                    short_name = category.split("–")[0].strip() if "–" in category else category[:35]
                    
                    owasp_table.add_row(
                        short_name,
                        str(count),
                        f"[{color}]{status}[/{color}]"
                    )
                
                self.console.print(owasp_table)
            
            # Display recommendations
            if "recommendations" in scan_data:
                recommendations = scan_data["recommendations"][:5]  # Top 5
                rec_text = "\n".join([f"• {rec.get('title', 'N/A')}: {rec.get('description', 'N/A')}" for rec in recommendations])
                
                self.console.print(Panel(
                    rec_text,
                    title="[bold yellow]🎯 Top Recommendations[/bold yellow]",
                    border_style="yellow"
                ))
            
        except Exception as e:
            self.console.print(f"[red]❌ Error reading scan report: {e}[/red]")

    def show_security_guide(self):
        """Display OWASP Top 10 security guide"""
        self.console.print(Panel(
            "[bold red]📖 OWASP Top 10 2021 Security Guide[/bold red]",
            border_style="red"
        ))
        
        guide_options = [
            "📋 Full OWASP Top 10 Overview",
            "🔍 A01:2021 – Broken Access Control",
            "🔐 A02:2021 – Cryptographic Failures", 
            "💉 A03:2021 – Injection",
            "🏗️  A04:2021 – Insecure Design",
            "⚙️  A05:2021 – Security Misconfiguration",
            "📦 A06:2021 – Vulnerable Components",
            "🆔 A07:2021 – Authentication Failures",
            "🔒 A08:2021 – Data Integrity Failures",
            "📊 A09:2021 – Logging Failures",
            "🌐 A10:2021 – Server-Side Request Forgery",
            "⬅️  Back to Main Menu"
        ]
        
        for i, option in enumerate(guide_options, 1):
            self.console.print(f"{i}. {option}")
        
        choice = IntPrompt.ask(
            "\n[cyan]Select topic (1-12)[/cyan]",
            choices=[str(i) for i in range(1, len(guide_options) + 1)]
        )
        
        if choice == 1:
            self.show_full_owasp_overview()
        elif 2 <= choice <= 11:
            self.show_owasp_detail(choice - 2)

    def show_full_owasp_overview(self):
        """Show full OWASP Top 10 overview"""
        overview_text = """
🛡️ OWASP Top 10 2021 represents a broad consensus about the most critical security risks to web applications.

The Top 10 categories are:

[bold red]A01:2021 – Broken Access Control[/bold red]
Restrictions on authenticated users not properly enforced. Moved up from #5.

[bold red]A02:2021 – Cryptographic Failures[/bold red]  
Previously known as Sensitive Data Exposure, focuses on failures related to cryptography.

[bold red]A03:2021 – Injection[/bold red]
User-supplied data not validated, filtered, or sanitized by the application.

[bold red]A04:2021 – Insecure Design[/bold red]
New category for 2021, focuses on risks related to design and architectural flaws.

[bold red]A05:2021 – Security Misconfiguration[/bold red]
Missing appropriate security hardening across any part of the application stack.

[bold red]A06:2021 – Vulnerable and Outdated Components[/bold red]
Previously Known Vulnerabilities, you are likely at risk if you do not know versions.

[bold red]A07:2021 – Identification and Authentication Failures[/bold red]
Previously Broken Authentication, confirms identity, authentication, and session management.

[bold red]A08:2021 – Software and Data Integrity Failures[/bold red]
New category for 2021, focuses on making assumptions about software updates and CI/CD pipelines.

[bold red]A09:2021 – Security Logging and Monitoring Failures[/bold red]
Previously Insufficient Logging & Monitoring, this category helps detect, escalate, and respond to breaches.

[bold red]A10:2021 – Server-Side Request Forgery[/bold red]
New category for 2021. SSRF flaws occur when a web application fetches remote resources.
        """
        
        self.console.print(Panel(overview_text, title="OWASP Top 10 2021 Overview", border_style="red"))
        
        self.console.print("\n[dim]Press Enter to continue...[/dim]")
        input()

    def show_owasp_detail(self, category_index: int):
        """Show detailed information for a specific OWASP category"""
        categories = [
            {
                "title": "A01:2021 – Broken Access Control",
                "description": "Access control enforces policy such that users cannot act outside of their intended permissions.",
                "examples": [
                    "Violation of principle of least privilege",
                    "Bypassing access control checks by modifying URL",
                    "Elevation of privilege (acting as admin without being logged in)",
                    "Metadata manipulation (JWT token, cookie manipulation)",
                    "CORS misconfiguration allowing API access from unauthorized origins"
                ],
                "prevention": [
                    "Implement access control mechanisms once and re-use",
                    "Model access controls to enforce record ownership",
                    "Disable web server directory listing",
                    "Log access control failures and alert admins",
                    "Rate limit API and controller access"
                ]
            },
            {
                "title": "A02:2021 – Cryptographic Failures",
                "description": "Many web applications and APIs do not properly protect sensitive data.",
                "examples": [
                    "Transmitting data in clear text (HTTP, FTP, SMTP)",
                    "Using old or weak cryptographic algorithms",
                    "Default crypto keys in use or weak crypto keys generated",
                    "Crypto not enforced (missing HTTP security headers)",
                    "Server certificate and trust chain not properly validated"
                ],
                "prevention": [
                    "Classify data processed and stored by application",
                    "Don't store sensitive data unnecessarily",
                    "Encrypt all sensitive data at rest",
                    "Ensure up-to-date and strong standard algorithms",
                    "Use proper key management"
                ]
            }
            # Add more categories as needed
        ]
        
        if category_index < len(categories):
            category = categories[category_index]
            
            detail_text = f"""
[bold red]{category['title']}[/bold red]

[bold yellow]Description:[/bold yellow]
{category['description']}

[bold yellow]Common Examples:[/bold yellow]
"""
            for example in category['examples']:
                detail_text += f"• {example}\n"
            
            detail_text += f"""
[bold yellow]How to Prevent:[/bold yellow]
"""
            for prevention in category['prevention']:
                detail_text += f"• {prevention}\n"
            
            self.console.print(Panel(detail_text, title=category['title'], border_style="red"))
        
        self.console.print("\n[dim]Press Enter to continue...[/dim]")
        input()

    def run_scan_with_config(self, config: ScanConfig) -> Optional[ScanResults]:
        """Run security scan with given configuration"""
        if not ZAP_AVAILABLE:
            self.console.print("[red]❌ ZAP Python API not available. Please install: pip install python-owasp-zap-v2.4[/red]")
            return None
        
        self.console.print(Panel(
            f"[bold green]🚀 Starting Security Scan[/bold green]\n\n"
            f"[yellow]Target:[/yellow] {config.target_url}\n"
            f"[yellow]Context:[/yellow] {config.context_name}\n"
            f"[yellow]Spider Depth:[/yellow] {config.spider_depth}\n"
            f"[yellow]AJAX Spider:[/yellow] {'Enabled' if config.ajax_spider_enabled else 'Disabled'}\n"
            f"[yellow]Timeout:[/yellow] {config.timeout} seconds",
            border_style="green"
        ))
        
        # Store config
        self.config = config
        
        try:
            # Initialize ZAP connection
            self.zap = ZAPv2(
                proxies={
                    'http': f'http://{config.zap_proxy_host}:{config.zap_proxy_port}',
                    'https': f'http://{config.zap_proxy_host}:{config.zap_proxy_port}'
                },
                apikey=config.api_key
            )
            
            # Test connection
            self.zap.core.version
            self.console.print("✅ ZAP API connection established")
            
        except Exception as e:
            self.console.print(f"[red]❌ Failed to connect to ZAP: {e}[/red]")
            self.console.print("[yellow]💡 Try starting ZAP container from the ZAP Management menu[/yellow]")
            return None
        
        start_time = time.time()
        scan_id = f"jarvis_scan_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        try:
            # Setup context
            self.console.print("\n[yellow]⚙️  Setting up scan context...[/yellow]")
            context_id = self.zap.context.new_context(config.context_name)
            self.zap.context.include_in_context(config.context_name, f"{config.target_url}.*")
            
            # Run spider scan
            self.console.print(f"\n[yellow]🕷️  Starting spider scan...[/yellow]")
            spider_scan_id = self.zap.spider.scan(
                config.target_url,
                maxchildren=config.spider_max_children,
                contextname=config.context_name
            )
            
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                console=self.console
            ) as progress:
                
                task = progress.add_task("Spider scanning...", total=100)
                
                while int(self.zap.spider.status(spider_scan_id)) < 100:
                    progress.update(task, completed=int(self.zap.spider.status(spider_scan_id)))
                    time.sleep(2)
                
                progress.update(task, completed=100)
            
            spider_urls = self.zap.spider.results(spider_scan_id)
            self.console.print(f"✅ Spider scan completed. Found {len(spider_urls)} URLs")
            
            # Run AJAX spider if enabled
            ajax_urls = []
            if config.ajax_spider_enabled:
                self.console.print(f"\n[yellow]🕸️  Starting AJAX spider scan...[/yellow]")
                self.zap.ajaxSpider.scan(config.target_url)
                
                with Progress(
                    SpinnerColumn(),
                    TextColumn("[progress.description]{task.description}"),
                    console=self.console
                ) as progress:
                    
                    task = progress.add_task("AJAX spider scanning...")
                    
                    while self.zap.ajaxSpider.status == "running":
                        progress.update(task)
                        time.sleep(3)
                
                ajax_urls = self.zap.ajaxSpider.results("start", "count") or []
                self.console.print(f"✅ AJAX spider completed. Found {len(ajax_urls)} additional URLs")
            
            # Run active scan
            self.console.print(f"\n[yellow]🎯 Starting active security scan...[/yellow]")
            all_urls = list(set(spider_urls + ajax_urls))
            
            # Limit URLs for demo (scan first 5 URLs)
            scan_urls = all_urls[:5] if len(all_urls) > 5 else all_urls
            
            for url in scan_urls:
                active_scan_id = self.zap.ascan.scan(
                    url,
                    policy=config.active_scan_policy,
                    contextid=context_id
                )
                
                with Progress(
                    SpinnerColumn(),
                    TextColumn(f"[progress.description]Scanning {url[:50]}..."),
                    BarColumn(),
                    TaskProgressColumn(),
                    console=self.console
                ) as progress:
                    
                    task = progress.add_task("Active scanning...", total=100)
                    
                    while int(self.zap.ascan.status(active_scan_id)) < 100:
                        progress.update(task, completed=int(self.zap.ascan.status(active_scan_id)))
                        time.sleep(3)
                    
                    progress.update(task, completed=100)
            
            # Get vulnerabilities
            alerts = self.zap.core.alerts()
            vulnerabilities = []
            
            for alert in alerts:
                vuln = VulnerabilityResult(
                    name=alert.get('alert', ''),
                    risk=alert.get('risk', ''),
                    confidence=alert.get('confidence', ''),
                    url=alert.get('url', ''),
                    param=alert.get('param', ''),
                    attack=alert.get('attack', ''),
                    evidence=alert.get('evidence', ''),
                    description=alert.get('description', ''),
                    solution=alert.get('solution', ''),
                    reference=alert.get('reference', ''),
                    cwe_id=alert.get('cweid', ''),
                    wasc_id=alert.get('wascid', ''),
                    source_id=alert.get('sourceid', '')
                )
                vulnerabilities.append(vuln)
            
            # Categorize vulnerabilities by OWASP Top 10
            owasp_categorized = self.categorize_by_owasp_top10(vulnerabilities)
            
            # Generate summary
            summary = self.generate_summary(vulnerabilities)
            
            # Create results
            results = ScanResults(
                scan_id=scan_id,
                timestamp=datetime.now().isoformat(),
                target_url=config.target_url,
                duration=time.time() - start_time,
                vulnerabilities=vulnerabilities,
                spider_urls=spider_urls,
                ajax_spider_urls=ajax_urls,
                summary=summary,
                owasp_top10_coverage=owasp_categorized
            )
            
            # Display results
            self.display_scan_results(results)
            
            # Generate reports
            self.generate_reports(results)
            
            self.current_scan_results = results
            return results
            
        except KeyboardInterrupt:
            self.console.print("\n[yellow]⚠️  Scan interrupted by user[/yellow]")
            return None
        except Exception as e:
            self.console.print(f"\n[red]❌ Scan failed: {e}[/red]")
            return None

    def categorize_by_owasp_top10(self, vulnerabilities: List[VulnerabilityResult]) -> Dict[str, List[VulnerabilityResult]]:
        """Categorize vulnerabilities by OWASP Top 10"""
        categorized = {category: [] for category in self.owasp_top10_mapping.keys()}
        uncategorized = []
        
        for vuln in vulnerabilities:
            categorized_flag = False
            for category, patterns in self.owasp_top10_mapping.items():
                if any(pattern.lower() in vuln.name.lower() for pattern in patterns):
                    categorized[category].append(vuln)
                    categorized_flag = True
                    break
            
            if not categorized_flag:
                uncategorized.append(vuln)
        
        if uncategorized:
            categorized["Uncategorized"] = uncategorized
            
        return categorized

    def generate_summary(self, vulnerabilities: List[VulnerabilityResult]) -> Dict[str, int]:
        """Generate vulnerability summary"""
        summary = {"High": 0, "Medium": 0, "Low": 0, "Informational": 0}
        
        for vuln in vulnerabilities:
            risk = vuln.risk.title()
            if risk in summary:
                summary[risk] += 1
        
        return summary

    def display_scan_results(self, results: ScanResults):
        """Display scan results in formatted tables"""
        self.console.print(f"\n[bold green]✅ Scan completed in {results.duration:.1f} seconds![/bold green]")
        
        # Summary table
        summary_table = Table(title="📊 Vulnerability Summary", box=box.ROUNDED)
        summary_table.add_column("Risk Level", style="bold")
        summary_table.add_column("Count", justify="center")
        summary_table.add_column("Percentage", justify="center")
        
        total = sum(results.summary.values())
        colors = {"High": "red", "Medium": "yellow", "Low": "blue", "Informational": "green"}
        
        for risk, count in results.summary.items():
            percentage = f"{(count/total*100):.1f}%" if total > 0 else "0%"
            summary_table.add_row(
                f"[{colors.get(risk, 'white')}]{risk}[/{colors.get(risk, 'white')}]",
                str(count),
                percentage
            )
        
        self.console.print(summary_table)
        
        # OWASP Top 10 table
        owasp_table = Table(title="🛡️ OWASP Top 10 Coverage", box=box.ROUNDED)
        owasp_table.add_column("OWASP Category", style="bold", width=40)
        owasp_table.add_column("Issues Found", justify="center")
        owasp_table.add_column("Status")
        
        for category, vulns in results.owasp_top10_coverage.items():
            if category == "Uncategorized":
                continue
            count = len(vulns)
            status = "✅ Tested" if count > 0 else "🔍 No Issues Found"
            color = "red" if count > 0 else "green"
            
            # Shorten category name for display
            short_name = category.split("–")[0].strip() if "–" in category else category[:38]
            
            owasp_table.add_row(
                short_name,
                str(count),
                f"[{color}]{status}[/{color}]"
            )
        
        self.console.print(owasp_table)
        
        # Show top vulnerabilities if any found
        if results.vulnerabilities:
            vuln_table = Table(title="🚨 Top Vulnerabilities Found", box=box.ROUNDED)
            vuln_table.add_column("Vulnerability", style="bold", width=25)
            vuln_table.add_column("Risk", justify="center", width=10)
            vuln_table.add_column("URL", width=35)
            vuln_table.add_column("Parameter", width=15)
            
            # Show top 10 vulnerabilities
            for vuln in results.vulnerabilities[:10]:
                color = colors.get(vuln.risk, 'white')
                vuln_table.add_row(
                    vuln.name[:23] + ("..." if len(vuln.name) > 23 else ""),
                    f"[{color}]{vuln.risk}[/{color}]",
                    vuln.url[:33] + ("..." if len(vuln.url) > 33 else ""),
                    vuln.param[:13] + ("..." if len(vuln.param) > 13 else "")
                )
            
            self.console.print(vuln_table)

    def generate_reports(self, results: ScanResults):
        """Generate comprehensive reports"""
        self.console.print(f"\n[yellow]📄 Generating reports...[/yellow]")
        
        output_dir = Path(self.config.output_dir) / results.scan_id
        output_dir.mkdir(parents=True, exist_ok=True)
        
        try:
            # Generate enhanced JSON report
            self.generate_enhanced_json_report(results, output_dir)
            
            # Generate CSV report
            self.generate_csv_report(results, output_dir)
            
            # Generate HTML report
            self.generate_html_report(results, output_dir)
            
            self.console.print(f"✅ Reports generated in: {output_dir}")
            
        except Exception as e:
            self.console.print(f"[red]❌ Report generation failed: {e}[/red]")

    def generate_enhanced_json_report(self, results: ScanResults, output_path: Path):
        """Generate enhanced JSON report"""
        # Calculate additional metrics
        risk_metrics = self.calculate_risk_metrics(results)
        
        enhanced_data = {
            "scan_metadata": {
                "scan_id": results.scan_id,
                "timestamp": results.timestamp,
                "target_url": results.target_url,
                "duration": results.duration,
                "report_generated": datetime.now().isoformat()
            },
            "summary": {
                "total_vulnerabilities": len(results.vulnerabilities),
                "risk_distribution": results.summary,
                "urls_tested": len(results.spider_urls),
                "ajax_urls_found": len(results.ajax_spider_urls)
            },
            "risk_analysis": risk_metrics,
            "owasp_top10_analysis": self.analyze_owasp_coverage(results),
            "vulnerabilities": [asdict(vuln) for vuln in results.vulnerabilities],
            "discovered_urls": {
                "spider_urls": results.spider_urls,
                "ajax_urls": results.ajax_spider_urls
            },
            "recommendations": self.generate_recommendations(results)
        }
        
        json_file = output_path / "enhanced_security_report.json"
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump(enhanced_data, f, indent=2, default=str)

    def generate_csv_report(self, results: ScanResults, output_path: Path):
        """Generate CSV report"""
        csv_file = output_path / "vulnerabilities_report.csv"
        
        fieldnames = [
            'name', 'risk', 'confidence', 'url', 'param', 'attack',
            'evidence', 'description', 'solution', 'reference',
            'cwe_id', 'wasc_id'
        ]
        
        with open(csv_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            
            for vuln in results.vulnerabilities:
                writer.writerow(asdict(vuln))

    def generate_html_report(self, results: ScanResults, output_path: Path):
        """Generate basic HTML report"""
        html_file = output_path / "security_report.html"
        
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>JARVIS DAST Security Report</title>
            <style>
                body {{ font-family: 'Segoe UI', sans-serif; margin: 40px; background: #f5f5f5; }}
                .container {{ max-width: 1200px; margin: 0 auto; background: white; padding: 30px; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
                .header {{ text-align: center; border-bottom: 3px solid #1f77b4; padding-bottom: 20px; margin-bottom: 30px; }}
                .risk-high {{ color: #d62728; font-weight: bold; }}
                .risk-medium {{ color: #ff7f0e; font-weight: bold; }}
                .risk-low {{ color: #2ca02c; font-weight: bold; }}
                .risk-informational {{ color: #1f77b4; font-weight: bold; }}
                .summary-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin: 20px 0; }}
                .summary-card {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px; border-radius: 8px; text-align: center; }}
                .vuln-table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
                .vuln-table th, .vuln-table td {{ border: 1px solid #ddd; padding: 12px; text-align: left; }}
                .vuln-table th {{ background-color: #1f77b4; color: white; }}
                .vuln-table tr:nth-child(even) {{ background-color: #f2f2f2; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>🛡️ JARVIS DAST Security Report</h1>
                    <p><strong>Target:</strong> {results.target_url}</p>
                    <p><strong>Scan ID:</strong> {results.scan_id}</p>
                    <p><strong>Generated:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
                </div>
                
                <div class="summary-grid">
                    <div class="summary-card">
                        <h3>Total Vulnerabilities</h3>
                        <h2>{len(results.vulnerabilities)}</h2>
                    </div>
                    <div class="summary-card">
                        <h3>High Risk</h3>
                        <h2>{results.summary.get('High', 0)}</h2>
                    </div>
                    <div class="summary-card">
                        <h3>Medium Risk</h3>
                        <h2>{results.summary.get('Medium', 0)}</h2>
                    </div>
                    <div class="summary-card">
                        <h3>URLs Tested</h3>
                        <h2>{len(results.spider_urls)}</h2>
                    </div>
                </div>
                
                <h2>🚨 Vulnerability Details</h2>
                <table class="vuln-table">
                    <thead>
                        <tr>
                            <th>Vulnerability</th>
                            <th>Risk</th>
                            <th>URL</th>
                            <th>Parameter</th>
                            <th>Description</th>
                        </tr>
                    </thead>
                    <tbody>
        """
        
        # Add vulnerability rows
        for vuln in results.vulnerabilities:
            html_content += f"""
                        <tr>
                            <td>{vuln.name}</td>
                            <td class="risk-{vuln.risk.lower()}">{vuln.risk}</td>
                            <td>{vuln.url[:60]}{'...' if len(vuln.url) > 60 else ''}</td>
                            <td>{vuln.param}</td>
                            <td>{vuln.description[:100]}{'...' if len(vuln.description) > 100 else ''}</td>
                        </tr>
            """
        
        html_content += """
                    </tbody>
                </table>
                
                <div style="margin-top: 40px; text-align: center; color: #666; border-top: 1px solid #ddd; padding-top: 20px;">
                    <p>Report generated by JARVIS DAST Security Scanner</p>
                    <p>Powered by OWASP ZAP</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        with open(html_file, 'w', encoding='utf-8') as f:
            f.write(html_content)

    def calculate_risk_metrics(self, results: ScanResults) -> Dict[str, Any]:
        """Calculate risk metrics"""
        total_vulns = len(results.vulnerabilities)
        high_risk = results.summary.get('High', 0)
        medium_risk = results.summary.get('Medium', 0)
        low_risk = results.summary.get('Low', 0)
        
        # Calculate risk score (weighted)
        risk_score = (high_risk * 10) + (medium_risk * 5) + (low_risk * 1)
        
        # Determine overall risk level
        if high_risk > 5:
            overall_risk = "Critical"
        elif high_risk > 0:
            overall_risk = "High"
        elif medium_risk > 5:
            overall_risk = "Medium"
        else:
            overall_risk = "Low"
        
        return {
            "total_vulnerabilities": total_vulns,
            "risk_score": risk_score,
            "overall_risk": overall_risk,
            "high_risk_percentage": (high_risk / total_vulns * 100) if total_vulns > 0 else 0
        }

    def analyze_owasp_coverage(self, results: ScanResults) -> Dict[str, Any]:
        """Analyze OWASP Top 10 coverage"""
        owasp_analysis = {}
        
        for category, vulns in results.owasp_top10_coverage.items():
            if category != "Uncategorized":
                owasp_analysis[category] = {
                    "vulnerability_count": len(vulns),
                    "tested": len(vulns) > 0
                }
        
        return owasp_analysis

    def generate_recommendations(self, results: ScanResults) -> List[Dict[str, str]]:
        """Generate security recommendations"""
        recommendations = []
        
        high_risk_count = results.summary.get('High', 0)
        medium_risk_count = results.summary.get('Medium', 0)
        
        if high_risk_count > 0:
            recommendations.append({
                "priority": "Critical",
                "title": "Address High-Risk Vulnerabilities Immediately",
                "description": f"Found {high_risk_count} high-risk vulnerabilities requiring immediate attention.",
                "action": "Review and patch all high-risk issues within 24-48 hours"
            })
        
        if medium_risk_count > 3:
            recommendations.append({
                "priority": "High", 
                "title": "Systematic Review of Medium-Risk Issues",
                "description": f"Multiple medium-risk vulnerabilities ({medium_risk_count}) detected.",
                "action": "Plan remediation within 30 days"
            })
        
        # Add generic recommendations
        recommendations.extend([
            {
                "priority": "Medium",
                "title": "Implement Security Headers",
                "description": "Ensure proper security headers are configured",
                "action": "Add CSP, X-Frame-Options, HSTS headers"
            },
            {
                "priority": "Low",
                "title": "Regular Security Testing",
                "description": "Establish regular security testing schedule",
                "action": "Implement automated security testing in CI/CD"
            }
        ])
        
        return recommendations[:8]  # Limit to top 8

    def run_main_loop(self):
        """Main application loop"""
        self.display_banner()
        
        while True:
            try:
                choice = self.show_main_menu()
                
                if choice == "❌ Exit":
                    self.console.print("\n[bold green]👋 Thank you for using JARVIS DAST Scanner![/bold green]")
                    break
                    
                elif choice == "🚀 Quick Scan":
                    config = self.quick_scan_setup()
                    if config:
                        self.run_scan_with_config(config)
                        
                elif choice == "⚙️  Custom Configuration":
                    config = self.custom_scan_configuration()
                    if config:
                        self.run_scan_with_config(config)
                        
                elif choice == "📋 Scan Profiles":
                    config = self.display_scan_profiles()
                    if config:
                        self.run_scan_with_config(config)
                        
                elif choice == "🐳 ZAP Management":
                    self.zap_management()
                    
                elif choice == "📊 View Results":
                    self.view_scan_results()
                    
                elif choice == "📖 Security Guide":
                    self.show_security_guide()
                    
                elif choice == "⚡ Settings":
                    self.configure_zap()
                
                # Pause before returning to menu (except for exit)
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
    """Entry point for JARVIS DAST"""
    parser = argparse.ArgumentParser(description="JARVIS DAST - Comprehensive Security Testing Tool")
    parser.add_argument("--config", help="Configuration file path")
    parser.add_argument("--target", help="Target URL", default="http://localhost:9000")
    parser.add_argument("--quick", action="store_true", help="Run quick scan with defaults")
    
    args = parser.parse_args()
    
    try:
        scanner = JarvisDAST()
        
        if args.quick:
            # Run quick scan without TUI
            config = ScanConfig(target_url=args.target)
            scanner.run_scan_with_config(config)
        else:
            # Run full TUI
            scanner.run_main_loop()
            
    except KeyboardInterrupt:
        print("\n\nExiting JARVIS DAST...")
        sys.exit(0)
    except Exception as e:
        print(f"Fatal error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()