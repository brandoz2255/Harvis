#!/usr/bin/env python3
"""
Configuration checker for Vibe Files
This checks for common configuration issues that could cause problems
"""

import os
import sys
import importlib.util

def check_environment_variables():
    """Check required environment variables"""
    print("🔍 CHECKING ENVIRONMENT VARIABLES")
    print("=" * 40)
    
    # Check database URL
    db_url = os.getenv("DATABASE_URL")
    if db_url:
        print(f"✅ DATABASE_URL is set")
        # Hide password for security
        safe_url = db_url.replace(db_url.split('@')[0].split('//')[1], "***") if '@' in db_url else db_url
        print(f"   Value: {safe_url}")
    else:
        print("⚠️  DATABASE_URL not set, using default")
        print("   Default: postgresql://pguser:pgpassword@pgsql-db:5432/database")
    
    # Check JWT secret
    jwt_secret = os.getenv("JWT_SECRET")
    if jwt_secret and jwt_secret != "key":
        print("✅ JWT_SECRET is set to custom value")
    else:
        print("⚠️  JWT_SECRET using default value 'key'")
        print("   Consider setting a secure secret in production")
    
    # Check Ollama API key
    ollama_key = os.getenv("OLLAMA_API_KEY")
    if ollama_key and ollama_key != "key":
        print("✅ OLLAMA_API_KEY is set")
    else:
        print("ℹ️  OLLAMA_API_KEY using default")

def check_python_dependencies():
    """Check if required Python packages are installed"""
    print("\n🔍 CHECKING PYTHON DEPENDENCIES")
    print("=" * 40)
    
    required_packages = [
        'fastapi',
        'asyncpg',
        'pydantic',
        'uvicorn',
        'python-jose',
        'passlib',
        'bcrypt'
    ]
    
    missing_packages = []
    
    for package in required_packages:
        try:
            spec = importlib.util.find_spec(package.replace('-', '_'))
            if spec is not None:
                print(f"✅ {package} is installed")
            else:
                print(f"❌ {package} is NOT installed")
                missing_packages.append(package)
        except ImportError:
            print(f"❌ {package} is NOT installed")
            missing_packages.append(package)
    
    if missing_packages:
        print(f"\n⚠️  MISSING PACKAGES: {', '.join(missing_packages)}")
        print("Install them with: pip install " + " ".join(missing_packages))
        return False
    
    return True

def check_file_structure():
    """Check if required files exist"""
    print("\n🔍 CHECKING FILE STRUCTURE")
    print("=" * 40)
    
    required_files = [
        'main.py',
        'vibecoding/__init__.py',
        'vibecoding/files.py',
        'auth_utils.py'
    ]
    
    missing_files = []
    
    for file_path in required_files:
        if os.path.exists(file_path):
            print(f"✅ {file_path} exists")
        else:
            print(f"❌ {file_path} is MISSING")
            missing_files.append(file_path)
    
    if missing_files:
        print(f"\n⚠️  MISSING FILES: {', '.join(missing_files)}")
        return False
    
    return True

def check_import_issues():
    """Check for potential import issues"""
    print("\n🔍 CHECKING IMPORT ISSUES")
    print("=" * 40)
    
    try:
        # Test importing main modules
        print("Testing imports...")
        
        # Test FastAPI import
        from fastapi import FastAPI
        print("✅ FastAPI import successful")
        
        # Test asyncpg import
        import asyncpg
        print("✅ asyncpg import successful")
        
        # Test auth utils import
        sys.path.append('.')
        from auth_utils import get_current_user
        print("✅ auth_utils import successful")
        
        # Test vibecoding import
        from vibecoding import files_router
        print("✅ vibecoding.files_router import successful")
        
        return True
        
    except ImportError as e:
        print(f"❌ Import error: {e}")
        return False
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return False

def check_port_availability():
    """Check if the default port is available"""
    print("\n🔍 CHECKING PORT AVAILABILITY")
    print("=" * 40)
    
    import socket
    
    def is_port_open(host, port):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(1)
                result = s.connect_ex((host, port))
                return result == 0
        except:
            return False
    
    port = 8000
    if is_port_open('localhost', port):
        print(f"⚠️  Port {port} is already in use")
        print("   This might be your server running, or another application")
    else:
        print(f"✅ Port {port} is available")

def generate_startup_command():
    """Generate the correct startup command"""
    print("\n🚀 STARTUP COMMAND")
    print("=" * 40)
    
    print("To start your server, use one of these commands:")
    print()
    print("Option 1 (recommended):")
    print("   uvicorn main:app --reload --host 0.0.0.0 --port 8000")
    print()
    print("Option 2:")
    print("   python main.py")
    print()
    print("Option 3 (with specific Python version):")
    print("   python3 main.py")

def main():
    """Main configuration check"""
    print("⚙️  VIBE FILES CONFIGURATION CHECKER")
    print("This will check for common configuration issues")
    print("=" * 50)
    
    all_good = True
    
    # Run all checks
    check_environment_variables()
    
    if not check_python_dependencies():
        all_good = False
    
    if not check_file_structure():
        all_good = False
    
    if not check_import_issues():
        all_good = False
    
    check_port_availability()
    
    # Final report
    print("\n📋 CONFIGURATION REPORT")
    print("=" * 40)
    
    if all_good:
        print("🎉 CONFIGURATION LOOKS GOOD!")
        print("Your environment should be ready to run Vibe Files.")
        print()
        print("Next steps:")
        print("1. Start your server using the command below")
        print("2. Run the debug script: python debug_step_by_step.py")
        print("3. Test the functionality")
    else:
        print("⚠️  CONFIGURATION ISSUES DETECTED")
        print("Fix the issues above before starting the server.")
    
    generate_startup_command()

if __name__ == "__main__":
    main()