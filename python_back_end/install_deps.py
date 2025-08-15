#!/usr/bin/env python3
"""
Robust dependency installer for Docker builds
Handles retries, conflicts, and verification
"""

import subprocess
import sys
import time
import re
from typing import List, Set

def run_command(cmd: List[str], max_retries: int = 3) -> bool:
    """Run a command with retry logic"""
    for attempt in range(max_retries):
        try:
            print(f"Running: {' '.join(cmd)} (attempt {attempt + 1})")
            result = subprocess.run(cmd, check=True, capture_output=True, text=True)
            print(f"Success: {result.stdout}")
            return True
        except subprocess.CalledProcessError as e:
            print(f"Attempt {attempt + 1} failed: {e.stderr}")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)  # Exponential backoff
            else:
                print(f"Command failed after {max_retries} attempts: {' '.join(cmd)}")
                return False
    return False

def parse_requirements(requirements_file: str) -> List[str]:
    """Parse requirements file, excluding comments and empty lines"""
    packages = []
    try:
        with open(requirements_file, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    packages.append(line)
    except FileNotFoundError:
        print(f"Requirements file not found: {requirements_file}")
        return []
    return packages

def is_package_installed(package_name: str) -> bool:
    """Check if a package is installed"""
    # Extract base package name (remove version constraints)
    base_name = re.split(r'[>=<!\[]', package_name)[0]
    
    try:
        subprocess.run([sys.executable, '-c', f'import {base_name}'], 
                      check=True, capture_output=True)
        return True
    except subprocess.CalledProcessError:
        # Try common package name mappings
        name_mappings = {
            'python-jose': 'jose',
            'python-multipart': 'multipart',
            'beautifulsoup4': 'bs4',
            'pillow': 'PIL',
            'pyyaml': 'yaml',
            'requests': 'requests',
            'ddgs': 'ddgs',
        }
        
        mapped_name = name_mappings.get(base_name, base_name)
        if mapped_name != base_name:
            try:
                subprocess.run([sys.executable, '-c', f'import {mapped_name}'], 
                              check=True, capture_output=True)
                return True
            except subprocess.CalledProcessError:
                pass
        
        return False

def install_packages(packages: List[str]) -> bool:
    """Install packages with comprehensive retry logic"""
    print(f"Installing {len(packages)} packages...")
    
    # First attempt: install all packages at once
    print("Attempting batch installation...")
    if run_command([sys.executable, '-m', 'pip', 'install', '--no-cache-dir'] + packages):
        print("Batch installation successful!")
        return True
    
    # Second attempt: install all packages with force-reinstall
    print("Batch installation failed, trying with force-reinstall...")
    if run_command([sys.executable, '-m', 'pip', 'install', '--no-cache-dir', '--force-reinstall'] + packages):
        print("Force-reinstall successful!")
        return True
    
    # Third attempt: install packages individually
    print("Batch installation failed, trying individual packages...")
    failed_packages = []
    
    for package in packages:
        print(f"Installing individual package: {package}")
        if not run_command([sys.executable, '-m', 'pip', 'install', '--no-cache-dir', package]):
            failed_packages.append(package)
    
    if failed_packages:
        print(f"Failed to install {len(failed_packages)} packages: {failed_packages}")
        return False
    
    return True

def verify_installation(packages: List[str]) -> Set[str]:
    """Verify that all packages are properly installed"""
    print("Verifying package installations...")
    missing_packages = set()
    
    for package in packages:
        if not is_package_installed(package):
            missing_packages.add(package)
            print(f"Package not properly installed: {package}")
        else:
            print(f"Package verified: {package}")
    
    return missing_packages

def main():
    """Main installation process"""
    print("Starting robust dependency installation...")
    
    # Parse requirements
    packages = parse_requirements('requirements_no_torch.txt')
    if not packages:
        print("No packages to install")
        return
    
    print(f"Found {len(packages)} packages to install")
    
    # Install packages
    if not install_packages(packages):
        print("Installation failed!")
        sys.exit(1)
    
    # Verify installation
    missing = verify_installation(packages)
    
    if missing:
        print(f"Attempting to install {len(missing)} missing packages...")
        if not install_packages(list(missing)):
            print("Failed to install missing packages!")
            sys.exit(1)
        
        # Final verification
        still_missing = verify_installation(list(missing))
        if still_missing:
            print(f"Still missing packages: {still_missing}")
            sys.exit(1)
    
    print("All packages installed and verified successfully!")

if __name__ == '__main__':
    main()