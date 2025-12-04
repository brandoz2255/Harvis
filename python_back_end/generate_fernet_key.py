#!/usr/bin/env python3
"""
Generate a Fernet encryption key for GitHub OAuth token storage.

Usage:
    python generate_fernet_key.py

This will output a base64-encoded key that can be used as FERNET_KEY environment variable.
"""

from cryptography.fernet import Fernet

if __name__ == "__main__":
    key = Fernet.generate_key()
    print("=" * 60)
    print("Generated FERNET_KEY (copy this to your .env file):")
    print("=" * 60)
    print(key.decode())
    print("=" * 60)
    print("\nAdd this to your python_back_end/.env file:")
    print(f"FERNET_KEY={key.decode()}")
    print("\n⚠️  Keep this key secure! Do not commit it to version control.")

