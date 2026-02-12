"""Legacy Colab Migration Module

This module handles migration of legacy Google Colab files to the new VibeCode structure.
It detects files with "colab" in the name or .ipynb extensions and moves them to a
vibe_legacy directory for preservation.
"""

import logging
import os
from typing import List, Dict, Any
from datetime import datetime

logger = logging.getLogger(__name__)

# ─── Migration Functions ───────────────────────────────────────────────────────

async def migrate_legacy_colab_files(
    container_manager,
    session_id: str,
    workspace_path: str = "/workspace"
) -> Dict[str, Any]:
    """
    Migrate legacy Colab files to vibe_legacy directory
    
    This function:
    1. Detects files with "colab" in name (case-insensitive) or .ipynb extension
    2. Creates /workspace/vibe_legacy directory if needed
    3. Moves detected files to vibe_legacy
    4. Logs migration results
    
    Args:
        container_manager: ContainerManager instance
        session_id: Session ID for the container
        workspace_path: Base workspace path (default: /workspace)
    
    Returns:
        Dict with migration results including:
        - migrated_files: List of files that were migrated
        - total_count: Total number of files migrated
        - legacy_dir: Path to the legacy directory
        - timestamp: When migration occurred
    """
    
    logger.info(f"🔄 Starting legacy Colab migration for session {session_id}")
    
    migrated_files = []
    legacy_dir = f"{workspace_path}/vibe_legacy"
    
    try:
        # Step 1: Find all files with "colab" in name or .ipynb extension
        find_command = (
            f"find {workspace_path} -maxdepth 5 -type f "
            f"\\( -iname '*colab*' -o -name '*.ipynb' \\) "
            f"-not -path '{legacy_dir}/*' 2>/dev/null || true"
        )
        
        result = await container_manager.execute_command(
            session_id=session_id,
            command=find_command,
            workdir=workspace_path
        )
        
        if result.exit_code != 0 and result.exit_code != 1:
            logger.warning(f"⚠️ Find command had issues: {result.stderr}")
        
        # Parse found files
        found_files = [
            line.strip() 
            for line in result.stdout.strip().split('\n') 
            if line.strip() and line.strip() != workspace_path
        ]
        
        if not found_files:
            logger.info(f"✅ No legacy Colab files found in session {session_id}")
            return {
                "migrated_files": [],
                "total_count": 0,
                "legacy_dir": legacy_dir,
                "timestamp": datetime.now().isoformat(),
                "message": "No legacy files found"
            }
        
        logger.info(f"📁 Found {len(found_files)} potential legacy files")
        
        # Step 2: Create vibe_legacy directory
        mkdir_result = await container_manager.execute_command(
            session_id=session_id,
            command=f"mkdir -p {legacy_dir}",
            workdir=workspace_path
        )
        
        if mkdir_result.exit_code != 0:
            logger.error(f"❌ Failed to create legacy directory: {mkdir_result.stderr}")
            raise Exception(f"Failed to create legacy directory: {mkdir_result.stderr}")
        
        logger.info(f"✅ Created legacy directory: {legacy_dir}")
        
        # Step 3: Move each file to vibe_legacy, preserving directory structure
        for file_path in found_files:
            try:
                # Get relative path from workspace
                rel_path = file_path.replace(workspace_path + '/', '')
                
                # Skip if already in vibe_legacy
                if rel_path.startswith('vibe_legacy/'):
                    continue
                
                # Create subdirectory structure in vibe_legacy if needed
                file_dir = os.path.dirname(rel_path)
                if file_dir:
                    mkdir_cmd = f"mkdir -p {legacy_dir}/{file_dir}"
                    await container_manager.execute_command(
                        session_id=session_id,
                        command=mkdir_cmd,
                        workdir=workspace_path
                    )
                
                # Move the file
                target_path = f"{legacy_dir}/{rel_path}"
                move_cmd = f"mv '{file_path}' '{target_path}'"
                
                move_result = await container_manager.execute_command(
                    session_id=session_id,
                    command=move_cmd,
                    workdir=workspace_path
                )
                
                if move_result.exit_code == 0:
                    migrated_files.append({
                        "original_path": file_path,
                        "new_path": target_path,
                        "filename": os.path.basename(file_path)
                    })
                    logger.info(f"✅ Migrated: {rel_path} -> vibe_legacy/{rel_path}")
                else:
                    logger.warning(f"⚠️ Failed to migrate {file_path}: {move_result.stderr}")
                    
            except Exception as e:
                logger.error(f"❌ Error migrating {file_path}: {e}")
                continue
        
        # Step 4: Create a README in vibe_legacy
        readme_content = """# Legacy Colab Files

This directory contains files that were automatically migrated from the legacy Google Colab system.

**Migration Date:** {timestamp}
**Files Migrated:** {count}

These files have been preserved for your reference. You can:
- Review and update them for use with VibeCode
- Delete them if no longer needed
- Keep them as backup

The VibeCode IDE provides a modern, VSCode-like experience with:
- Full file management
- Interactive terminal
- Code execution
- AI assistance

For questions, refer to the VibeCode documentation.
""".format(
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            count=len(migrated_files)
        )
        
        # Write README
        readme_cmd = f"cat > {legacy_dir}/README.md << 'EOFREADME'\n{readme_content}\nEOFREADME"
        await container_manager.execute_command(
            session_id=session_id,
            command=readme_cmd,
            workdir=workspace_path
        )
        
        logger.info(f"✅ Migration complete: {len(migrated_files)} files migrated")
        
        return {
            "migrated_files": migrated_files,
            "total_count": len(migrated_files),
            "legacy_dir": legacy_dir,
            "timestamp": datetime.now().isoformat(),
            "message": f"Successfully migrated {len(migrated_files)} legacy files"
        }
        
    except Exception as e:
        logger.error(f"❌ Migration failed for session {session_id}: {e}")
        return {
            "migrated_files": migrated_files,
            "total_count": len(migrated_files),
            "legacy_dir": legacy_dir,
            "timestamp": datetime.now().isoformat(),
            "error": str(e),
            "message": f"Migration partially completed with errors"
        }


async def check_migration_needed(
    container_manager,
    session_id: str,
    workspace_path: str = "/workspace"
) -> bool:
    """
    Check if migration is needed for a session
    
    Returns True if legacy files are detected, False otherwise
    """
    
    try:
        # Check for legacy marker file
        marker_path = f"{workspace_path}/.vibe_migration_complete"
        check_marker = await container_manager.execute_command(
            session_id=session_id,
            command=f"test -f {marker_path} && echo 'exists' || echo 'not_exists'",
            workdir=workspace_path
        )
        
        if "exists" in check_marker.stdout:
            logger.info(f"✅ Migration already completed for session {session_id}")
            return False
        
        # Check for legacy files
        find_command = (
            f"find {workspace_path} -maxdepth 5 -type f "
            f"\\( -iname '*colab*' -o -name '*.ipynb' \\) "
            f"-not -path '{workspace_path}/vibe_legacy/*' 2>/dev/null | head -1"
        )
        
        result = await container_manager.execute_command(
            session_id=session_id,
            command=find_command,
            workdir=workspace_path
        )
        
        has_legacy_files = bool(result.stdout.strip())
        
        if has_legacy_files:
            logger.info(f"🔍 Legacy files detected in session {session_id}")
        
        return has_legacy_files
        
    except Exception as e:
        logger.error(f"❌ Error checking migration status: {e}")
        return False


async def mark_migration_complete(
    container_manager,
    session_id: str,
    workspace_path: str = "/workspace"
) -> bool:
    """
    Mark migration as complete by creating a marker file
    """
    
    try:
        marker_path = f"{workspace_path}/.vibe_migration_complete"
        marker_content = f"Migration completed at {datetime.now().isoformat()}"
        
        result = await container_manager.execute_command(
            session_id=session_id,
            command=f"echo '{marker_content}' > {marker_path}",
            workdir=workspace_path
        )
        
        if result.exit_code == 0:
            logger.info(f"✅ Marked migration complete for session {session_id}")
            return True
        else:
            logger.warning(f"⚠️ Failed to mark migration complete: {result.stderr}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Error marking migration complete: {e}")
        return False
