#!/usr/bin/env python3
"""
Advanced Report Generator for OWASP ZAP DAST Scanner
Professional security reporting with multiple output formats
"""

import os
import json
import yaml
import csv
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
import base64
from io import BytesIO

# Rich formatting
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

# HTML/PDF generation
try:
    from jinja2 import Template, Environment, FileSystemLoader
    JINJA2_AVAILABLE = True
except ImportError:
    JINJA2_AVAILABLE = False

try:
    import matplotlib.pyplot as plt
    import matplotlib.patches as patches
    from matplotlib.figure import Figure
    import seaborn as sns
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False

try:
    import plotly.graph_objects as go
    import plotly.express as px
    from plotly.subplots import make_subplots
    PLOTLY_AVAILABLE = True  
except ImportError:
    PLOTLY_AVAILABLE = False

# Import our scanner types
try:
    from zap_scanner import ScanResults, VulnerabilityResult
except ImportError:
    print("Warning: zap_scanner.py not found. Some features may not work.")

@dataclass
class ReportConfig:
    """Configuration for report generation"""
    template_dir: str = "./templates"
    output_format: str = "html"  # html, pdf, json, xml, csv, markdown
    include_charts: bool = True
    include_executive_summary: bool = True
    include_technical_details: bool = True
    include_remediation: bool = True
    branding: Dict[str, str] = None
    
    def __post_init__(self):
        if self.branding is None:
            self.branding = {
                "company_name": "Security Team",
                "report_title": "DAST Security Assessment",
                "logo_path": "",
                "primary_color": "#1f77b4",
                "secondary_color": "#ff7f0e"
            }

class AdvancedReportGenerator:
    """Advanced report generator with multiple formats and visualizations"""
    
    def __init__(self, config: ReportConfig = None):
        self.config = config or ReportConfig()
        self.console = Console()
        
        # Create template directory if it doesn't exist
        Path(self.config.template_dir).mkdir(parents=True, exist_ok=True)
        
        # Initialize Jinja2 environment if available
        if JINJA2_AVAILABLE:
            self.jinja_env = Environment(
                loader=FileSystemLoader(self.config.template_dir)
            )
        
        # Initialize matplotlib style
        if MATPLOTLIB_AVAILABLE:
            plt.style.use('seaborn-v0_8')
            sns.set_palette("husl")

    def generate_comprehensive_report(self, results: ScanResults, output_path: Path) -> Dict[str, str]:
        """Generate comprehensive security report in multiple formats"""
        self.console.print(f"[yellow]📄 Generating comprehensive report...[/yellow]")
        
        generated_files = {}
        
        # Generate different report formats
        if self.config.output_format in ["html", "all"]:
            html_file = self.generate_html_report(results, output_path)
            generated_files["html"] = str(html_file)
        
        if self.config.output_format in ["json", "all"]:
            json_file = self.generate_enhanced_json_report(results, output_path)
            generated_files["json"] = str(json_file)
        
        if self.config.output_format in ["csv", "all"]:
            csv_file = self.generate_csv_report(results, output_path)
            generated_files["csv"] = str(csv_file)
        
        if self.config.output_format in ["markdown", "all"]:
            md_file = self.generate_markdown_report(results, output_path)
            generated_files["markdown"] = str(md_file)
        
        if self.config.output_format in ["xml", "all"]:
            xml_file = self.generate_xml_report(results, output_path)
            generated_files["xml"] = str(xml_file)
        
        # Generate executive summary
        if self.config.include_executive_summary:
            exec_file = self.generate_executive_summary(results, output_path)
            generated_files["executive_summary"] = str(exec_file)
        
        return generated_files

    def generate_html_report(self, results: ScanResults, output_path: Path) -> Path:
        """Generate comprehensive HTML report"""
        html_file = output_path / "comprehensive_security_report.html"
        
        # Generate charts if enabled
        charts = {}
        if self.config.include_charts and MATPLOTLIB_AVAILABLE:
            charts = self.generate_visualization_charts(results, output_path)
        
        # Create HTML template
        html_template = self.create_html_template()
        
        # Prepare template data
        template_data = {
            "scan_results": results,
            "config": self.config,
            "charts": charts,
            "generation_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "risk_summary": self.calculate_risk_metrics(results),
            "owasp_analysis": self.analyze_owasp_coverage(results),
            "recommendations": self.generate_recommendations(results)
        }
        
        # Render HTML
        if JINJA2_AVAILABLE:
            template = Template(html_template)
            html_content = template.render(**template_data)
        else:
            html_content = self.create_basic_html_report(results)
        
        # Write HTML file
        with open(html_file, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        return html_file

    def generate_enhanced_json_report(self, results: ScanResults, output_path: Path) -> Path:
        """Generate enhanced JSON report with additional analysis"""
        json_file = output_path / "enhanced_security_report.json"
        
        # Enhance results with additional analysis
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
            "risk_analysis": self.calculate_risk_metrics(results),
            "owasp_top10_analysis": self.analyze_owasp_coverage(results),
            "vulnerabilities": [asdict(vuln) for vuln in results.vulnerabilities],
            "discovered_urls": {
                "spider_urls": results.spider_urls,
                "ajax_urls": results.ajax_spider_urls
            },
            "recommendations": self.generate_recommendations(results),
            "compliance_status": self.assess_compliance_status(results)
        }
        
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump(enhanced_data, f, indent=2, default=str)
        
        return json_file

    def generate_csv_report(self, results: ScanResults, output_path: Path) -> Path:
        """Generate CSV report for vulnerability data"""
        csv_file = output_path / "vulnerabilities_report.csv"
        
        fieldnames = [
            'name', 'risk', 'confidence', 'url', 'param', 'attack',
            'evidence', 'description', 'solution', 'reference',
            'cwe_id', 'wasc_id', 'owasp_category'
        ]
        
        with open(csv_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            
            for vuln in results.vulnerabilities:
                vuln_dict = asdict(vuln)
                # Add OWASP category
                vuln_dict['owasp_category'] = self.categorize_vulnerability(vuln)
                writer.writerow(vuln_dict)
        
        return csv_file

    def generate_markdown_report(self, results: ScanResults, output_path: Path) -> Path:
        """Generate Markdown report"""
        md_file = output_path / "security_report.md"
        
        markdown_content = self.create_markdown_template(results)
        
        with open(md_file, 'w', encoding='utf-8') as f:
            f.write(markdown_content)
        
        return md_file

    def generate_xml_report(self, results: ScanResults, output_path: Path) -> Path:
        """Generate XML report"""
        xml_file = output_path / "security_report.xml"
        
        xml_content = self.create_xml_template(results)
        
        with open(xml_file, 'w', encoding='utf-8') as f:
            f.write(xml_content)
        
        return xml_file

    def generate_executive_summary(self, results: ScanResults, output_path: Path) -> Path:
        """Generate executive summary report"""
        summary_file = output_path / "executive_summary.html"
        
        # Calculate key metrics
        risk_metrics = self.calculate_risk_metrics(results)
        total_vulns = len(results.vulnerabilities)
        high_risk_count = results.summary.get('High', 0)
        
        # Generate executive summary HTML
        summary_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Executive Security Summary</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 40px; }}
                .header {{ color: #1f77b4; border-bottom: 2px solid #1f77b4; padding-bottom: 10px; }}
                .risk-high {{ color: #d62728; font-weight: bold; }}
                .risk-medium {{ color: #ff7f0e; font-weight: bold; }}
                .risk-low {{ color: #2ca02c; font-weight: bold; }}
                .summary-box {{ background: #f8f9fa; padding: 20px; margin: 20px 0; border-left: 4px solid #1f77b4; }}
                .recommendations {{ background: #fff3cd; padding: 15px; margin: 20px 0; border-radius: 5px; }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>🛡️ Security Assessment Executive Summary</h1>
                <p><strong>Target:</strong> {results.target_url}</p>
                <p><strong>Scan Date:</strong> {results.timestamp}</p>
                <p><strong>Duration:</strong> {results.duration:.1f} seconds</p>
            </div>
            
            <div class="summary-box">
                <h2>📊 Key Findings</h2>
                <ul>
                    <li><strong>Total Vulnerabilities:</strong> {total_vulns}</li>
                    <li class="risk-high">High Risk Issues: {results.summary.get('High', 0)}</li>
                    <li class="risk-medium">Medium Risk Issues: {results.summary.get('Medium', 0)}</li>
                    <li class="risk-low">Low Risk Issues: {results.summary.get('Low', 0)}</li>
                    <li><strong>URLs Tested:</strong> {len(results.spider_urls)}</li>
                </ul>
            </div>
            
            <div class="recommendations">
                <h2>🎯 Priority Recommendations</h2>
                <ol>
                    {self.format_executive_recommendations(results)}
                </ol>
            </div>
            
            <div class="summary-box">
                <h2>📈 Risk Assessment</h2>
                <p><strong>Overall Risk Level:</strong> {risk_metrics['overall_risk']}</p>
                <p><strong>Remediation Priority:</strong> {risk_metrics['remediation_priority']}</p>
            </div>
        </body>
        </html>
        """
        
        with open(summary_file, 'w', encoding='utf-8') as f:
            f.write(summary_html)
        
        return summary_file

    def generate_visualization_charts(self, results: ScanResults, output_path: Path) -> Dict[str, str]:
        """Generate visualization charts for the report"""
        charts = {}
        
        if not MATPLOTLIB_AVAILABLE:
            return charts
        
        # Risk distribution pie chart
        if results.summary:
            charts['risk_distribution'] = self.create_risk_distribution_chart(results, output_path)
        
        # OWASP Top 10 coverage bar chart
        charts['owasp_coverage'] = self.create_owasp_coverage_chart(results, output_path)
        
        # Vulnerability trend (if historical data available)
        charts['severity_breakdown'] = self.create_severity_breakdown_chart(results, output_path)
        
        return charts

    def create_risk_distribution_chart(self, results: ScanResults, output_path: Path) -> str:
        """Create risk distribution pie chart"""
        fig, ax = plt.subplots(figsize=(10, 8))
        
        # Prepare data
        risks = list(results.summary.keys())
        counts = list(results.summary.values())
        colors = ['#d62728', '#ff7f0e', '#2ca02c', '#1f77b4']  # Red, Orange, Green, Blue
        
        # Create pie chart
        wedges, texts, autotexts = ax.pie(
            counts, 
            labels=risks, 
            colors=colors[:len(risks)],
            autopct='%1.1f%%',
            startangle=90,
            explode=[0.05 if risk == 'High' else 0 for risk in risks]
        )
        
        ax.set_title('Vulnerability Risk Distribution', fontsize=16, fontweight='bold')
        
        # Save chart
        chart_path = output_path / 'risk_distribution_chart.png'
        plt.savefig(chart_path, dpi=300, bbox_inches='tight')
        plt.close()
        
        return str(chart_path)

    def create_owasp_coverage_chart(self, results: ScanResults, output_path: Path) -> str:
        """Create OWASP Top 10 coverage bar chart"""
        fig, ax = plt.subplots(figsize=(14, 8))
        
        # Prepare OWASP data
        owasp_categories = []
        vulnerability_counts = []
        
        for category, vulns in results.owasp_top10_coverage.items():
            if category != "Uncategorized":
                # Shorten category names for display
                short_name = category.split("–")[0].strip()
                owasp_categories.append(short_name)
                vulnerability_counts.append(len(vulns))
        
        # Create bar chart
        bars = ax.bar(range(len(owasp_categories)), vulnerability_counts, 
                     color='skyblue', edgecolor='navy', alpha=0.7)
        
        # Customize chart
        ax.set_xlabel('OWASP Top 10 Categories', fontsize=12, fontweight='bold')
        ax.set_ylabel('Number of Vulnerabilities', fontsize=12, fontweight='bold')
        ax.set_title('OWASP Top 10 Coverage Analysis', fontsize=16, fontweight='bold')
        ax.set_xticks(range(len(owasp_categories)))
        ax.set_xticklabels(owasp_categories, rotation=45, ha='right')
        
        # Add value labels on bars
        for bar in bars:
            height = bar.get_height()
            if height > 0:
                ax.text(bar.get_x() + bar.get_width()/2., height,
                       f'{int(height)}', ha='center', va='bottom')
        
        plt.tight_layout()
        
        # Save chart
        chart_path = output_path / 'owasp_coverage_chart.png'
        plt.savefig(chart_path, dpi=300, bbox_inches='tight')
        plt.close()
        
        return str(chart_path)

    def create_severity_breakdown_chart(self, results: ScanResults, output_path: Path) -> str:
        """Create severity breakdown horizontal bar chart"""
        fig, ax = plt.subplots(figsize=(12, 6))
        
        # Prepare data
        severities = ['High', 'Medium', 'Low', 'Informational']
        counts = [results.summary.get(sev, 0) for sev in severities]
        colors = ['#d62728', '#ff7f0e', '#2ca02c', '#1f77b4']
        
        # Create horizontal bar chart
        bars = ax.barh(severities, counts, color=colors, alpha=0.8)
        
        # Customize chart
        ax.set_xlabel('Number of Vulnerabilities', fontsize=12, fontweight='bold')
        ax.set_title('Vulnerability Severity Breakdown', fontsize=16, fontweight='bold')
        
        # Add value labels
        for i, (bar, count) in enumerate(zip(bars, counts)):
            if count > 0:
                ax.text(count + 0.1, bar.get_y() + bar.get_height()/2,
                       f'{count}', ha='left', va='center', fontweight='bold')
        
        plt.tight_layout()
        
        # Save chart
        chart_path = output_path / 'severity_breakdown_chart.png'
        plt.savefig(chart_path, dpi=300, bbox_inches='tight')
        plt.close()
        
        return str(chart_path)

    def calculate_risk_metrics(self, results: ScanResults) -> Dict[str, Any]:
        """Calculate comprehensive risk metrics"""
        total_vulns = len(results.vulnerabilities)
        high_risk = results.summary.get('High', 0)
        medium_risk = results.summary.get('Medium', 0)
        low_risk = results.summary.get('Low', 0)
        
        # Calculate risk score (weighted)
        risk_score = (high_risk * 10) + (medium_risk * 5) + (low_risk * 1)
        
        # Determine overall risk level
        if high_risk > 5:
            overall_risk = "Critical"
        elif high_risk > 0 or medium_risk > 10:
            overall_risk = "High"
        elif medium_risk > 0 or low_risk > 20:
            overall_risk = "Medium"
        else:
            overall_risk = "Low"
        
        # Remediation priority
        if high_risk > 0:
            remediation_priority = "Immediate"
        elif medium_risk > 5:
            remediation_priority = "Within 30 days"
        elif medium_risk > 0:
            remediation_priority = "Within 90 days"
        else:
            remediation_priority = "Next maintenance cycle"
        
        return {
            "total_vulnerabilities": total_vulns,
            "risk_score": risk_score,
            "overall_risk": overall_risk,
            "remediation_priority": remediation_priority,
            "high_risk_percentage": (high_risk / total_vulns * 100) if total_vulns > 0 else 0,
            "coverage_score": len(results.spider_urls) / 100  # Rough coverage metric
        }

    def analyze_owasp_coverage(self, results: ScanResults) -> Dict[str, Any]:
        """Analyze OWASP Top 10 coverage"""
        owasp_analysis = {}
        
        for category, vulns in results.owasp_top10_coverage.items():
            if category != "Uncategorized":
                owasp_analysis[category] = {
                    "vulnerability_count": len(vulns),
                    "tested": len(vulns) > 0,
                    "risk_levels": {}
                }
                
                # Analyze risk levels within category
                for vuln in vulns:
                    risk = vuln.risk
                    owasp_analysis[category]["risk_levels"][risk] = \
                        owasp_analysis[category]["risk_levels"].get(risk, 0) + 1
        
        return owasp_analysis

    def generate_recommendations(self, results: ScanResults) -> List[Dict[str, str]]:
        """Generate security recommendations based on findings"""
        recommendations = []
        
        # High-level recommendations based on findings
        high_risk_count = results.summary.get('High', 0)
        medium_risk_count = results.summary.get('Medium', 0)
        
        if high_risk_count > 0:
            recommendations.append({
                "priority": "Critical",
                "title": "Address High-Risk Vulnerabilities Immediately",
                "description": f"Found {high_risk_count} high-risk vulnerabilities that require immediate attention.",
                "action": "Review and patch all high-risk issues within 24-48 hours"
            })
        
        if medium_risk_count > 5:
            recommendations.append({
                "priority": "High",
                "title": "Systematic Review of Medium-Risk Issues",
                "description": f"Multiple medium-risk vulnerabilities ({medium_risk_count}) detected.",
                "action": "Plan remediation within 30 days and implement preventive measures"
            })
        
        # OWASP-specific recommendations
        for category, vulns in results.owasp_top10_coverage.items():
            if len(vulns) > 0 and category != "Uncategorized":
                recommendations.append({
                    "priority": "Medium",
                    "title": f"Address {category.split('–')[1].strip()} Issues",
                    "description": f"Found {len(vulns)} vulnerabilities in this OWASP category.",
                    "action": "Implement category-specific security controls and testing"
                })
        
        # General security recommendations
        recommendations.extend([
            {
                "priority": "Medium",
                "title": "Implement Security Headers",
                "description": "Ensure proper security headers are implemented",
                "action": "Add CSP, X-Frame-Options, HSTS, and other security headers"
            },
            {
                "priority": "Low",
                "title": "Regular Security Testing",
                "description": "Establish regular security testing schedule",
                "action": "Implement automated security testing in CI/CD pipeline"
            }
        ])
        
        return recommendations[:10]  # Limit to top 10 recommendations

    def assess_compliance_status(self, results: ScanResults) -> Dict[str, Any]:
        """Assess compliance with security standards"""
        high_risk = results.summary.get('High', 0)
        medium_risk = results.summary.get('Medium', 0)
        
        # Basic compliance assessment
        compliance_status = {
            "overall_compliance": "Non-Compliant" if high_risk > 0 else "Partially Compliant",
            "owasp_top10_coverage": len([cat for cat, vulns in results.owasp_top10_coverage.items() if len(vulns) == 0 and cat != "Uncategorized"]),
            "security_score": max(0, 100 - (high_risk * 20) - (medium_risk * 5)),
            "compliance_gaps": []
        }
        
        if high_risk > 0:
            compliance_status["compliance_gaps"].append("High-risk vulnerabilities present")
        
        if medium_risk > 10:
            compliance_status["compliance_gaps"].append("Excessive medium-risk vulnerabilities")
        
        return compliance_status

    def categorize_vulnerability(self, vuln: VulnerabilityResult) -> str:
        """Categorize vulnerability into OWASP Top 10"""
        # Simple categorization logic
        vuln_name = vuln.name.lower()
        
        if any(term in vuln_name for term in ['sql injection', 'injection']):
            return "A03:2021 – Injection"
        elif any(term in vuln_name for term in ['xss', 'cross site scripting']):
            return "A03:2021 – Injection"
        elif any(term in vuln_name for term in ['access control', 'authorization']):
            return "A01:2021 – Broken Access Control"
        elif any(term in vuln_name for term in ['authentication', 'session']):
            return "A07:2021 – Identification and Authentication Failures"
        else:
            return "Other"

    def format_executive_recommendations(self, results: ScanResults) -> str:
        """Format recommendations for executive summary"""
        recommendations = self.generate_recommendations(results)
        
        formatted = ""
        for i, rec in enumerate(recommendations[:5], 1):  # Top 5 recommendations
            formatted += f"<li><strong>{rec['title']}</strong>: {rec['description']}</li>"
        
        return formatted

    def create_html_template(self) -> str:
        """Create comprehensive HTML template"""
        return """
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>{{ config.branding.report_title }}</title>
            <style>
                body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; margin: 0; padding: 20px; background-color: #f5f5f5; }
                .container { max-width: 1200px; margin: 0 auto; background: white; padding: 30px; border-radius: 10px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }
                .header { text-align: center; border-bottom: 3px solid {{ config.branding.primary_color }}; padding-bottom: 20px; margin-bottom: 30px; }
                .risk-high { color: #d62728; font-weight: bold; }
                .risk-medium { color: #ff7f0e; font-weight: bold; }
                .risk-low { color: #2ca02c; font-weight: bold; }
                .risk-info { color: #1f77b4; font-weight: bold; }
                .summary-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 20px; margin: 20px 0; }
                .summary-card { background: #f8f9fa; padding: 20px; border-radius: 8px; border-left: 4px solid {{ config.branding.primary_color }}; }
                .vuln-table { width: 100%; border-collapse: collapse; margin-top: 20px; }
                .vuln-table th, .vuln-table td { border: 1px solid #ddd; padding: 12px; text-align: left; }
                .vuln-table th { background-color: {{ config.branding.primary_color }}; color: white; }
                .chart-container { text-align: center; margin: 30px 0; }
                .recommendations { background: #fff3cd; padding: 20px; margin: 20px 0; border-radius: 8px; border-left: 4px solid #ffc107; }
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>🛡️ {{ config.branding.report_title }}</h1>
                    <p><strong>Target:</strong> {{ scan_results.target_url }}</p>
                    <p><strong>Scan ID:</strong> {{ scan_results.scan_id }}</p>
                    <p><strong>Generated:</strong> {{ generation_time }}</p>
                </div>
                
                <div class="summary-grid">
                    <div class="summary-card">
                        <h3>📊 Total Vulnerabilities</h3>
                        <h2>{{ scan_results.vulnerabilities|length }}</h2>
                    </div>
                    <div class="summary-card">
                        <h3>🚨 High Risk</h3>
                        <h2 class="risk-high">{{ scan_results.summary.High or 0 }}</h2>
                    </div>
                    <div class="summary-card">
                        <h3>⚠️ Medium Risk</h3>
                        <h2 class="risk-medium">{{ scan_results.summary.Medium or 0 }}</h2>
                    </div>
                    <div class="summary-card">
                        <h3>🔍 URLs Tested</h3>
                        <h2>{{ scan_results.spider_urls|length }}</h2>
                    </div>
                </div>
                
                {% if charts %}
                <div class="chart-container">
                    <h2>📈 Vulnerability Analysis</h2>
                    {% for chart_name, chart_path in charts.items() %}
                    <img src="{{ chart_path }}" alt="{{ chart_name }}" style="max-width: 100%; margin: 10px;">
                    {% endfor %}
                </div>
                {% endif %}
                
                <div class="recommendations">
                    <h2>🎯 Key Recommendations</h2>
                    <ol>
                    {% for rec in recommendations[:5] %}
                        <li><strong>{{ rec.title }}</strong>: {{ rec.description }}</li>
                    {% endfor %}
                    </ol>
                </div>
                
                <h2>🔍 Detailed Vulnerability Report</h2>
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
                    {% for vuln in scan_results.vulnerabilities %}
                        <tr>
                            <td>{{ vuln.name }}</td>
                            <td class="risk-{{ vuln.risk.lower() }}">{{ vuln.risk }}</td>
                            <td>{{ vuln.url }}</td>
                            <td>{{ vuln.param }}</td>
                            <td>{{ vuln.description[:100] }}...</td>
                        </tr>
                    {% endfor %}
                    </tbody>
                </table>
                
                <div style="margin-top: 40px; text-align: center; color: #666;">
                    <p>Report generated by {{ config.branding.company_name }} DAST Scanner</p>
                </div>
            </div>
        </body>
        </html>
        """

    def create_basic_html_report(self, results: ScanResults) -> str:
        """Create basic HTML report without Jinja2"""
        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Security Assessment Report</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 40px; }}
                .header {{ color: #1f77b4; border-bottom: 2px solid #1f77b4; padding-bottom: 10px; }}
                .risk-high {{ color: #d62728; font-weight: bold; }}
                .risk-medium {{ color: #ff7f0e; font-weight: bold; }}
                .risk-low {{ color: #2ca02c; font-weight: bold; }}
                table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
                th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
                th {{ background-color: #f2f2f2; }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>🛡️ Security Assessment Report</h1>
                <p><strong>Target:</strong> {results.target_url}</p>
                <p><strong>Scan ID:</strong> {results.scan_id}</p>
                <p><strong>Total Vulnerabilities:</strong> {len(results.vulnerabilities)}</p>
            </div>
            
            <h2>Risk Summary</h2>
            <ul>
                <li class="risk-high">High: {results.summary.get('High', 0)}</li>
                <li class="risk-medium">Medium: {results.summary.get('Medium', 0)}</li>
                <li class="risk-low">Low: {results.summary.get('Low', 0)}</li>
            </ul>
            
            <h2>Vulnerabilities</h2>
            <table>
                <tr>
                    <th>Name</th>
                    <th>Risk</th>
                    <th>URL</th>
                    <th>Description</th>
                </tr>
                {''.join([f"<tr><td>{vuln.name}</td><td class='risk-{vuln.risk.lower()}'>{vuln.risk}</td><td>{vuln.url}</td><td>{vuln.description[:100]}...</td></tr>" for vuln in results.vulnerabilities])}
            </table>
        </body>
        </html>
        """

    def create_markdown_template(self, results: ScanResults) -> str:
        """Create Markdown report template"""
        risk_metrics = self.calculate_risk_metrics(results)
        
        return f"""# 🛡️ Security Assessment Report

## Scan Information
- **Target URL:** {results.target_url}
- **Scan ID:** {results.scan_id}
- **Timestamp:** {results.timestamp}
- **Duration:** {results.duration:.1f} seconds

## Executive Summary
- **Total Vulnerabilities:** {len(results.vulnerabilities)}
- **Risk Score:** {risk_metrics['risk_score']}
- **Overall Risk Level:** {risk_metrics['overall_risk']}
- **Remediation Priority:** {risk_metrics['remediation_priority']}

## Risk Distribution
- **High:** {results.summary.get('High', 0)}
- **Medium:** {results.summary.get('Medium', 0)}
- **Low:** {results.summary.get('Low', 0)}
- **Informational:** {results.summary.get('Informational', 0)}

## OWASP Top 10 Coverage
{self._format_owasp_markdown(results)}

## Vulnerabilities Detail
{self._format_vulnerabilities_markdown(results)}

## Recommendations
{self._format_recommendations_markdown(results)}

---
*Report generated by JARVIS DAST Scanner*
"""

    def _format_owasp_markdown(self, results: ScanResults) -> str:
        """Format OWASP coverage for markdown"""
        output = ""
        for category, vulns in results.owasp_top10_coverage.items():
            if category != "Uncategorized":
                status = "✅ Tested" if len(vulns) > 0 else "🔍 No Issues Found"
                output += f"- **{category}:** {len(vulns)} vulnerabilities - {status}\n"
        return output

    def _format_vulnerabilities_markdown(self, results: ScanResults) -> str:
        """Format vulnerabilities for markdown"""
        output = ""
        for vuln in results.vulnerabilities[:20]:  # Limit to first 20
            output += f"""
### {vuln.name}
- **Risk:** {vuln.risk}
- **Confidence:** {vuln.confidence}
- **URL:** {vuln.url}
- **Parameter:** {vuln.param}
- **Description:** {vuln.description}
- **Solution:** {vuln.solution}

"""
        return output

    def _format_recommendations_markdown(self, results: ScanResults) -> str:
        """Format recommendations for markdown"""
        recommendations = self.generate_recommendations(results)
        output = ""
        for i, rec in enumerate(recommendations, 1):
            output += f"{i}. **{rec['title']}** ({rec['priority']} Priority)\n   - {rec['description']}\n   - Action: {rec['action']}\n\n"
        return output

    def create_xml_template(self, results: ScanResults) -> str:
        """Create XML report template"""
        vulnerabilities_xml = ""
        for vuln in results.vulnerabilities:
            vulnerabilities_xml += f"""
    <vulnerability>
        <name>{vuln.name}</name>
        <risk>{vuln.risk}</risk>
        <confidence>{vuln.confidence}</confidence>
        <url>{vuln.url}</url>
        <parameter>{vuln.param}</parameter>
        <description>{vuln.description}</description>
        <solution>{vuln.solution}</solution>
        <cwe_id>{vuln.cwe_id}</cwe_id>
        <wasc_id>{vuln.wasc_id}</wasc_id>
    </vulnerability>"""
        
        return f"""<?xml version="1.0" encoding="UTF-8"?>
<security_report>
    <scan_info>
        <scan_id>{results.scan_id}</scan_id>
        <timestamp>{results.timestamp}</timestamp>
        <target_url>{results.target_url}</target_url>
        <duration>{results.duration}</duration>
    </scan_info>
    <summary>
        <total_vulnerabilities>{len(results.vulnerabilities)}</total_vulnerabilities>
        <high_risk>{results.summary.get('High', 0)}</high_risk>
        <medium_risk>{results.summary.get('Medium', 0)}</medium_risk>
        <low_risk>{results.summary.get('Low', 0)}</low_risk>
        <informational>{results.summary.get('Informational', 0)}</informational>
    </summary>
    <vulnerabilities>{vulnerabilities_xml}
    </vulnerabilities>
</security_report>"""

def main():
    """Test the report generator"""
    console = Console()
    console.print("[green]Report Generator Test[/green]")
    
    # This would normally be called with actual scan results
    console.print("Report generator is ready for use with scan results.")

if __name__ == "__main__":
    main()