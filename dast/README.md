# JARVIS DAST - Security Testing Tool

A comprehensive Dynamic Application Security Testing (DAST) tool for the Jarvis web application, built with OWASP ZAP and Python.

## 🚀 Quick Start

### Prerequisites

1. **Docker** (for ZAP container)
2. **Python 3.7+**
3. **OWASP ZAP** (via Docker)

### Installation

1. Install Python dependencies:
```bash
pip install -r requirements.txt
```

2. Make the script executable:
```bash
chmod +x jarvis_dast.py
```

3. Start your Jarvis application:
```bash
# Make sure your web app is running on http://localhost:9000
docker-compose up -d
```

### Running the Tool

#### Interactive TUI Mode (Recommended)
```bash
python jarvis_dast.py
```

#### Quick Scan Mode  
```bash
python jarvis_dast.py --quick --target http://localhost:9000
```

## 🛡️ Features

### Core Capabilities
- **🕷️ Spider Scanning** - Automated web crawling
- **🕸️ AJAX Spider** - Modern web app discovery  
- **🎯 Active Scanning** - Security vulnerability detection
- **📊 OWASP Top 10** - Complete coverage analysis
- **📄 Multi-format Reports** - HTML, JSON, XML, CSV

### Scan Profiles
- **🚀 Quick Security Check** - Fast critical vulnerability scan (2-3 mins)
- **🔍 Comprehensive Audit** - Full OWASP Top 10 coverage (8-10 mins)
- **🔗 API Security Test** - REST API focused testing (4-5 mins)
- **🔐 Authentication Bypass** - Auth vulnerability specialization (3-4 mins)

### OWASP Top 10 2021 Coverage
- ✅ A01:2021 – Broken Access Control
- ✅ A02:2021 – Cryptographic Failures
- ✅ A03:2021 – Injection
- ✅ A04:2021 – Insecure Design
- ✅ A05:2021 – Security Misconfiguration
- ✅ A06:2021 – Vulnerable and Outdated Components
- ✅ A07:2021 – Identification and Authentication Failures
- ✅ A08:2021 – Software and Data Integrity Failures
- ✅ A09:2021 – Security Logging and Monitoring Failures
- ✅ A10:2021 – Server-Side Request Forgery

## 📋 TUI Menu Options

1. **🚀 Quick Scan** - Start immediate security scan with default settings
2. **⚙️ Custom Configuration** - Configure detailed scan parameters
3. **📋 Scan Profiles** - Select from predefined scanning profiles
4. **🐳 ZAP Management** - Manage ZAP container and services
5. **📊 View Results** - Browse and analyze scan reports
6. **📖 Security Guide** - Learn about OWASP Top 10 vulnerabilities
7. **⚡ Settings** - Application settings and preferences
8. **❌ Exit** - Close the application

## 🐳 ZAP Management

The tool includes built-in Docker management for OWASP ZAP:

- **🚀 Start ZAP Container** - Automatically pulls and starts ZAP
- **🛑 Stop ZAP Container** - Cleanly stops ZAP service
- **📊 Container Status** - Check ZAP container and API status
- **🔄 Restart ZAP Container** - Restart ZAP service
- **📋 View ZAP Logs** - Debug ZAP container issues

## 📊 Report Formats

### Generated Reports
- **HTML Report** - Professional web-based report with charts
- **JSON Report** - Enhanced machine-readable data with analysis
- **CSV Report** - Vulnerability data for spreadsheet analysis
- **XML Report** - Structured data for integration

### Report Location
```
./reports/jarvis_scan_YYYYMMDD_HHMMSS/
├── security_report.html
├── enhanced_security_report.json
├── vulnerabilities_report.csv
└── security_report.xml
```

## ⚙️ Configuration

### Default Configuration
```yaml
target_url: "http://localhost:9000"
backend_url: "http://localhost:8000"  
zap_proxy_host: "127.0.0.1"
zap_proxy_port: 8080
spider_depth: 5
ajax_spider_enabled: true
timeout: 300
output_dir: "./reports"
```

### Custom Configuration
Create a `config.yaml` file and use:
```bash
python jarvis_dast.py --config config.yaml
```

## 🔧 Troubleshooting

### Common Issues

#### ZAP Connection Failed
```
❌ Failed to connect to ZAP: Connection refused
```
**Solution:** Start ZAP container from the ZAP Management menu (option 4 → 1)

#### Target Application Not Accessible
```
⚠️ Target application not accessible
```
**Solution:** Ensure your Jarvis app is running on the specified URL

#### Missing Dependencies
```
ModuleNotFoundError: No module named 'zapv2'
```
**Solution:** Install requirements: `pip install -r requirements.txt`

### Manual ZAP Setup
If automatic Docker management fails:
```bash
docker run -d --name jarvis-zap -p 8080:8080 \
  owasp/zap2docker-stable zap.sh -daemon \
  -host 0.0.0.0 -port 8080 -config api.disablekey=true
```

## 🎯 Testing Your Jarvis Application

### Recommended Testing Flow
1. **Start with Quick Scan** - Get immediate security overview
2. **Run Comprehensive Audit** - Full OWASP Top 10 analysis
3. **Focus on API Testing** - Test backend API endpoints
4. **Authentication Testing** - Verify auth security

### Jarvis-Specific Endpoints Tested
- Authentication: `/api/auth/login`, `/api/auth/signup`
- Chat APIs: `/api/chat`, `/api/mic-chat`, `/api/research-chat`
- Voice: `/api/voice-transcribe`, `/api/audio/`
- AI: `/api/analyze-screen`, `/api/gemini-chat`
- n8n: `/api/n8n-automation`, `/api/n8n-workflows`
- System: `/api/settings`, `/api/ollama-models`

## 📈 Security Metrics

### Risk Levels
- **High** - Critical vulnerabilities requiring immediate attention
- **Medium** - Important security issues for planned remediation  
- **Low** - Minor security improvements
- **Informational** - Security observations and best practices

### OWASP Coverage Score
The tool provides complete coverage analysis showing:
- Which OWASP Top 10 categories were tested
- Number of vulnerabilities found per category
- Overall security posture assessment

## 🤝 Integration

### CI/CD Integration
```bash
# Quick headless scan for pipelines
python jarvis_dast.py --quick --target $TARGET_URL
```

### Custom Scripting
```python
from jarvis_dast import JarvisDAST, ScanConfig

scanner = JarvisDAST()
config = ScanConfig(target_url="http://localhost:9000")
results = scanner.run_scan_with_config(config)
```

## 📝 License

This tool is part of the Jarvis project and follows the same licensing terms.

## 🆘 Support

For issues and questions:
1. Check the troubleshooting section above
2. Review ZAP container logs via the TUI
3. Ensure all prerequisites are installed
4. Verify target application accessibility

---

**Happy Security Testing! 🛡️**