#!/usr/bin/env python3
"""
OWASP ZAP DAST Security Scanner for Jarvis Web Application
Comprehensive automated security testing with OWASP Top 10 coverage
"""

import os
import json
import time
import yaml
import subprocess
import requests
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
import argparse
import logging

# Rich TUI imports
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.panel import Panel
from rich.text import Text
from rich.prompt import Prompt, Confirm
from rich.layout import Layout
from rich.live import Live
from rich import box

# ZAP Python API
try:
    from zapv2 import ZAPv2
except ImportError:
    print("ZAP Python API not found. Install with: pip install python-owasp-zap-v2.4")
    exit(1)

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

class ZAPScanner:
    """Main ZAP scanner class"""
    
    def __init__(self, config: ScanConfig):
        self.config = config
        self.console = Console()
        self.zap = None
        self.scan_id = f"jarvis_scan_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.results = None
        
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
        
        # Setup logging
        self.setup_logging()
        
    def setup_logging(self):
        """Setup logging configuration"""
        log_dir = Path(self.config.output_dir) / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_dir / f"{self.scan_id}.log"),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)

    def display_banner(self):
        """Display application banner"""
        banner = """
╔══════════════════════════════════════════════════════════════════════════════╗
║                    🛡️  JARVIS DAST SECURITY SCANNER 🛡️                      ║
║                         OWASP ZAP Automation Tool                           ║
║                    Comprehensive Web Application Testing                     ║
╚══════════════════════════════════════════════════════════════════════════════╝
        """
        self.console.print(Panel(banner, style="bold blue"))

    def check_prerequisites(self) -> bool:
        """Check if ZAP and target are accessible"""
        self.console.print("\n[yellow]🔍 Checking prerequisites...[/yellow]")
        
        # Check if ZAP is running
        try:
            response = requests.get(f"http://{self.config.zap_proxy_host}:{self.config.zap_proxy_port}")
            self.console.print("✅ ZAP proxy is accessible")
        except requests.exceptions.ConnectionError:
            self.console.print("[red]❌ ZAP proxy not accessible. Please start ZAP first.[/red]")
            self.console.print(f"Expected ZAP at: http://{self.config.zap_proxy_host}:{self.config.zap_proxy_port}")
            return False
        
        # Check target application
        try:
            response = requests.get(self.config.target_url, timeout=10)
            self.console.print(f"✅ Target application accessible: {self.config.target_url}")
        except requests.exceptions.RequestException as e:
            self.console.print(f"[red]❌ Target application not accessible: {e}[/red]")
            return False
            
        return True

    def start_zap_daemon(self) -> bool:
        """Start ZAP daemon if not running"""
        self.console.print("\n[yellow]🚀 Starting ZAP daemon...[/yellow]")
        
        zap_command = [
            "zap.sh", "-daemon",
            "-host", self.config.zap_proxy_host,
            "-port", str(self.config.zap_proxy_port),
            "-config", "api.disablekey=true"
        ]
        
        if self.config.api_key:
            zap_command.extend(["-config", f"api.key={self.config.api_key}"])
        
        try:
            subprocess.Popen(zap_command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(10)  # Wait for ZAP to start
            return self.check_prerequisites()
        except FileNotFoundError:
            self.console.print("[red]❌ ZAP executable not found. Please ensure ZAP is installed.[/red]")
            return False

    def initialize_zap(self) -> bool:
        """Initialize ZAP connection"""
        try:
            self.zap = ZAPv2(
                proxies={
                    'http': f'http://{self.config.zap_proxy_host}:{self.config.zap_proxy_port}',
                    'https': f'http://{self.config.zap_proxy_host}:{self.config.zap_proxy_port}'
                },
                apikey=self.config.api_key
            )
            
            # Test connection
            self.zap.core.version
            self.console.print("✅ ZAP API connection established")
            return True
            
        except Exception as e:
            self.console.print(f"[red]❌ Failed to connect to ZAP API: {e}[/red]")
            return False

    def setup_context(self):
        """Setup ZAP context for the application"""
        self.console.print(f"\n[yellow]⚙️  Setting up context: {self.config.context_name}[/yellow]")
        
        try:
            # Create context
            context_id = self.zap.context.new_context(self.config.context_name)
            
            # Include URLs in context
            self.zap.context.include_in_context(self.config.context_name, f"{self.config.target_url}.*")
            self.zap.context.include_in_context(self.config.context_name, f"{self.config.backend_url}.*")
            
            # Set up authentication if credentials provided
            if self.config.auth_username and self.config.auth_password:
                self.setup_authentication(context_id)
                
            self.console.print("✅ Context setup completed")
            return context_id
            
        except Exception as e:
            self.console.print(f"[red]❌ Context setup failed: {e}[/red]")
            return None

    def setup_authentication(self, context_id: str):
        """Setup authentication for the scan"""
        self.console.print("[yellow]🔐 Setting up authentication...[/yellow]")
        
        try:
            # Setup form-based authentication
            login_url = f"{self.config.target_url}/api/auth/login"
            
            auth_method_id = self.zap.authentication.set_authentication_method(
                context_id,
                "formBasedAuthentication",
                f"loginUrl={login_url}&loginRequestData=username%3D{self.config.auth_username}%26password%3D{self.config.auth_password}"
            )
            
            # Create user
            user_id = self.zap.users.new_user(context_id, "testuser")
            self.zap.users.set_authentication_credentials(
                context_id, user_id,
                f"username={self.config.auth_username}&password={self.config.auth_password}"
            )
            self.zap.users.set_user_enabled(context_id, user_id, "true")
            
            self.console.print("✅ Authentication configured")
            
        except Exception as e:
            self.console.print(f"[yellow]⚠️  Authentication setup failed: {e}[/yellow]")

    def run_spider_scan(self) -> List[str]:
        """Run traditional spider scan"""
        self.console.print(f"\n[yellow]🕷️  Starting spider scan on {self.config.target_url}[/yellow]")
        
        scan_id = self.zap.spider.scan(
            self.config.target_url,
            maxchildren=self.config.spider_max_children,
            contextname=self.config.context_name
        )
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=self.console
        ) as progress:
            
            task = progress.add_task("Spider scanning...", total=100)
            
            while int(self.zap.spider.status(scan_id)) < 100:
                progress.update(task, completed=int(self.zap.spider.status(scan_id)))
                time.sleep(2)
            
            progress.update(task, completed=100)
        
        urls = self.zap.spider.results(scan_id)
        self.console.print(f"✅ Spider scan completed. Found {len(urls)} URLs")
        return urls

    def run_ajax_spider_scan(self) -> List[str]:
        """Run AJAX spider scan"""
        if not self.config.ajax_spider_enabled:
            return []
            
        self.console.print(f"\n[yellow]🕸️  Starting AJAX spider scan on {self.config.target_url}[/yellow]")
        
        self.zap.ajaxSpider.scan(self.config.target_url)
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            console=self.console
        ) as progress:
            
            task = progress.add_task("AJAX spider scanning...", total=None)
            
            while self.zap.ajaxSpider.status == "running":
                progress.update(task)
                time.sleep(2)
        
        urls = self.zap.ajaxSpider.results("start", "count")
        self.console.print(f"✅ AJAX spider scan completed. Found {len(urls)} additional URLs")
        return urls

    def run_active_scan(self, target_urls: List[str]) -> List[VulnerabilityResult]:
        """Run active security scan"""
        self.console.print(f"\n[yellow]🎯 Starting active security scan...[/yellow]")
        
        vulnerabilities = []
        
        for url in target_urls[:10]:  # Limit to first 10 URLs for demo
            scan_id = self.zap.ascan.scan(
                url,
                policy=self.config.active_scan_policy,
                contextid=self.config.context_name
            )
            
            with Progress(
                SpinnerColumn(),
                TextColumn(f"[progress.description]Scanning {url}..."),
                BarColumn(),
                TaskProgressColumn(),
                console=self.console
            ) as progress:
                
                task = progress.add_task("Active scanning...", total=100)
                
                while int(self.zap.ascan.status(scan_id)) < 100:
                    progress.update(task, completed=int(self.zap.ascan.status(scan_id)))
                    time.sleep(3)
                
                progress.update(task, completed=100)
        
        # Get all alerts
        alerts = self.zap.core.alerts()
        
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
        
        self.console.print(f"✅ Active scan completed. Found {len(vulnerabilities)} vulnerabilities")
        return vulnerabilities

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

    def display_results_table(self, results: ScanResults):
        """Display results in a formatted table"""
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
        owasp_table.add_column("OWASP Category", style="bold")
        owasp_table.add_column("Vulnerabilities Found", justify="center")
        owasp_table.add_column("Status")
        
        for category, vulns in results.owasp_top10_coverage.items():
            if category == "Uncategorized":
                continue
            count = len(vulns)
            status = "✅ Tested" if count > 0 else "🔍 No Issues Found"
            color = "red" if count > 0 else "green"
            
            owasp_table.add_row(
                category,
                str(count),
                f"[{color}]{status}[/{color}]"
            )
        
        self.console.print(owasp_table)

    def generate_reports(self, results: ScanResults):
        """Generate various report formats"""
        self.console.print(f"\n[yellow]📄 Generating reports...[/yellow]")
        
        output_dir = Path(self.config.output_dir) / self.scan_id
        output_dir.mkdir(parents=True, exist_ok=True)
        
        for format_type in self.config.report_formats:
            if format_type == "html":
                self.generate_html_report(results, output_dir)
            elif format_type == "json":
                self.generate_json_report(results, output_dir)
            elif format_type == "xml":
                self.generate_xml_report(results, output_dir)
        
        self.console.print(f"✅ Reports generated in: {output_dir}")

    def generate_html_report(self, results: ScanResults, output_dir: Path):
        """Generate HTML report"""
        try:
            html_report = self.zap.core.htmlreport()
            with open(output_dir / "security_report.html", "w") as f:
                f.write(html_report)
        except Exception as e:
            self.logger.error(f"HTML report generation failed: {e}")

    def generate_json_report(self, results: ScanResults, output_dir: Path):
        """Generate JSON report"""
        try:
            with open(output_dir / "security_report.json", "w") as f:
                json.dump(asdict(results), f, indent=2, default=str)
        except Exception as e:
            self.logger.error(f"JSON report generation failed: {e}")

    def generate_xml_report(self, results: ScanResults, output_dir: Path):
        """Generate XML report"""
        try:
            xml_report = self.zap.core.xmlreport()
            with open(output_dir / "security_report.xml", "w") as f:
                f.write(xml_report)
        except Exception as e:
            self.logger.error(f"XML report generation failed: {e}")

    def run_full_scan(self) -> ScanResults:
        """Run complete DAST scan"""
        start_time = time.time()
        
        self.console.print("\n[bold green]🚀 Starting comprehensive DAST scan...[/bold green]")
        
        # Setup context
        context_id = self.setup_context()
        
        # Run spider scans
        spider_urls = self.run_spider_scan()
        ajax_urls = self.run_ajax_spider_scan() if self.config.ajax_spider_enabled else []
        
        # Combine all discovered URLs
        all_urls = list(set(spider_urls + ajax_urls))
        
        # Run active scan
        vulnerabilities = self.run_active_scan(all_urls)
        
        # Categorize vulnerabilities
        owasp_categorized = self.categorize_by_owasp_top10(vulnerabilities)
        
        # Generate summary
        summary = self.generate_summary(vulnerabilities)
        
        # Create results object
        results = ScanResults(
            scan_id=self.scan_id,
            timestamp=datetime.now().isoformat(),
            target_url=self.config.target_url,
            duration=time.time() - start_time,
            vulnerabilities=vulnerabilities,
            spider_urls=spider_urls,
            ajax_spider_urls=ajax_urls,
            summary=summary,
            owasp_top10_coverage=owasp_categorized
        )
        
        self.results = results
        return results

def create_interactive_config() -> ScanConfig:
    """Create scan configuration interactively"""
    console = Console()
    
    console.print("\n[bold blue]🔧 SCAN CONFIGURATION[/bold blue]")
    
    # Basic configuration
    target_url = Prompt.ask("Target URL", default="http://localhost:9000")
    backend_url = Prompt.ask("Backend URL", default="http://localhost:8000")
    
    # Authentication
    use_auth = Confirm.ask("Configure authentication?", default=False)
    auth_username = ""
    auth_password = ""
    
    if use_auth:
        auth_username = Prompt.ask("Username")
        auth_password = Prompt.ask("Password", password=True)
    
    # Scan options
    spider_depth = int(Prompt.ask("Spider depth", default="5"))
    ajax_spider = Confirm.ask("Enable AJAX spider?", default=True)
    
    # Output options
    output_dir = Prompt.ask("Output directory", default="./reports")
    
    return ScanConfig(
        target_url=target_url,
        backend_url=backend_url,
        spider_depth=spider_depth,
        ajax_spider_enabled=ajax_spider,
        auth_username=auth_username,
        auth_password=auth_password,
        output_dir=output_dir
    )

def main():
    """Main function"""
    parser = argparse.ArgumentParser(description="OWASP ZAP DAST Scanner for Jarvis")
    parser.add_argument("--config", help="Configuration file path")
    parser.add_argument("--target", help="Target URL", default="http://localhost:9000")
    parser.add_argument("--interactive", action="store_true", help="Interactive configuration")
    parser.add_argument("--start-zap", action="store_true", help="Start ZAP daemon")
    
    args = parser.parse_args()
    
    # Initialize scanner
    if args.interactive:
        config = create_interactive_config()
    elif args.config and os.path.exists(args.config):
        with open(args.config) as f:
            config_data = yaml.safe_load(f)
            config = ScanConfig(**config_data)
    else:
        config = ScanConfig(target_url=args.target)
    
    scanner = ZAPScanner(config)
    scanner.display_banner()
    
    # Start ZAP if requested
    if args.start_zap:
        if not scanner.start_zap_daemon():
            return 1
    
    # Check prerequisites
    if not scanner.check_prerequisites():
        return 1
    
    # Initialize ZAP connection
    if not scanner.initialize_zap():
        return 1
    
    try:
        # Run full scan
        results = scanner.run_full_scan()
        
        # Display results
        scanner.display_results_table(results)
        
        # Generate reports
        scanner.generate_reports(results)
        
        scanner.console.print("\n[bold green]✅ DAST scan completed successfully![/bold green]")
        
        return 0
        
    except KeyboardInterrupt:
        scanner.console.print("\n[yellow]⚠️  Scan interrupted by user[/yellow]")
        return 1
    except Exception as e:
        scanner.console.print(f"\n[red]❌ Scan failed: {e}[/red]")
        return 1

if __name__ == "__main__":
    exit(main())