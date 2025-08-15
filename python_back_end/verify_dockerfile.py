#!/usr/bin/env python3
"""
Verify that the Dockerfile is properly structured for robust dependency installation
"""

import os
import re

def verify_dockerfile():
    """Verify the Dockerfile has proper dependency installation"""
    print("🔍 Verifying Dockerfile structure...")
    
    with open('Dockerfile', 'r') as f:
        content = f.read()
    
    # Check for required components
    checks = [
        ("pip upgrade", "pip install --no-cache-dir --upgrade pip"),
        ("PyTorch installation", "torch==2.6.0+cu124"),
        ("requirements filtering", "grep -v \"^torch\" requirements.txt"),
        ("robust installation script", "python3 install_deps.py"),
        ("fallback mechanism", "falling back to traditional method"),
        ("model cache", "--mount=type=cache"),
    ]
    
    all_passed = True
    
    for check_name, pattern in checks:
        if pattern in content:
            print(f"✅ {check_name}: Found")
        else:
            print(f"❌ {check_name}: Missing '{pattern}'")
            all_passed = False
    
    return all_passed

def verify_requirements():
    """Verify requirements.txt is properly structured"""
    print("\n🔍 Verifying requirements.txt...")
    
    if not os.path.exists('requirements.txt'):
        print("❌ requirements.txt not found")
        return False
    
    with open('requirements.txt', 'r') as f:
        lines = f.readlines()
    
    packages = [line.strip() for line in lines if line.strip() and not line.startswith('#')]
    
    print(f"✅ Found {len(packages)} packages")
    
    # Check for potentially problematic packages
    issues = []
    
    for package in packages:
        if 'torch' in package.lower() and '==' not in package:
            issues.append(f"PyTorch package without version pin: {package}")
    
    if issues:
        print("⚠️  Potential issues found:")
        for issue in issues:
            print(f"  - {issue}")
    
    return len(issues) == 0

def verify_install_script():
    """Verify the installation script exists and is properly structured"""
    print("\n🔍 Verifying install_deps.py...")
    
    if not os.path.exists('install_deps.py'):
        print("❌ install_deps.py not found")
        return False
    
    with open('install_deps.py', 'r') as f:
        content = f.read()
    
    required_functions = [
        'run_command',
        'parse_requirements', 
        'is_package_installed',
        'install_packages',
        'verify_installation',
        'main'
    ]
    
    all_functions_found = True
    
    for func in required_functions:
        if f"def {func}" in content:
            print(f"✅ Function {func}: Found")
        else:
            print(f"❌ Function {func}: Missing")
            all_functions_found = False
    
    return all_functions_found

def main():
    """Main verification process"""
    print("🐳 Verifying Python backend Docker build setup...\n")
    
    dockerfile_ok = verify_dockerfile()
    requirements_ok = verify_requirements()
    script_ok = verify_install_script()
    
    if dockerfile_ok and requirements_ok and script_ok:
        print("\n✅ All verifications passed! The Docker build should be robust.")
        print("\nKey improvements:")
        print("- PyTorch installed separately to avoid conflicts")
        print("- Robust retry mechanism with exponential backoff")
        print("- Individual package installation fallback")
        print("- Package verification after installation")
        print("- Traditional pip install fallback if script fails")
    else:
        print("\n❌ Some verifications failed. Please check the issues above.")
        return 1
    
    return 0

if __name__ == '__main__':
    exit(main())