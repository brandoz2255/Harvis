# Legacy Colab Migration Documentation

## Overview

The VibeCode IDE includes an automatic migration system that detects and moves legacy Google Colab files to a dedicated `vibe_legacy` directory. This ensures a clean transition from the old Colab system to the new VibeCode experience while preserving existing work.

## How It Works

### Automatic Detection

The migration system automatically runs when:
1. A container is created for the first time
2. A container is started for the first time

The system detects files that match either of these criteria:
- Files with "colab" in the name (case-insensitive)
- Files with `.ipynb` extension (Jupyter notebooks)

### Migration Process

When legacy files are detected, the system:

1. **Creates Legacy Directory**: Creates `/workspace/vibe_legacy/` if it doesn't exist
2. **Preserves Structure**: Maintains the original directory structure within `vibe_legacy`
3. **Moves Files**: Moves all detected files to the legacy directory
4. **Creates README**: Adds a README.md explaining the migration
5. **Marks Complete**: Creates a `.vibe_migration_complete` marker file to prevent re-running

### Files Migrated

Examples of files that will be migrated:
- `my_colab_notebook.ipynb`
- `colab_utils.py`
- `ColabHelper.js`
- `test_colab.sh`
- Any `.ipynb` file (Jupyter notebooks)

### Files NOT Migrated

Files already in the `vibe_legacy` directory are skipped to prevent recursive migration.

## Implementation Details

### Backend Module

The migration logic is implemented in `vibecoding/migration.py`:

```python
from vibecoding.migration import (
    migrate_legacy_colab_files,
    check_migration_needed,
    mark_migration_complete
)
```

### Key Functions

#### `migrate_legacy_colab_files(container_manager, session_id, workspace_path="/workspace")`

Performs the actual migration of legacy files.

**Returns:**
```python
{
    "migrated_files": [
        {
            "original_path": "/workspace/test_colab.py",
            "new_path": "/workspace/vibe_legacy/test_colab.py",
            "filename": "test_colab.py"
        }
    ],
    "total_count": 1,
    "legacy_dir": "/workspace/vibe_legacy",
    "timestamp": "2025-01-07T10:30:00",
    "message": "Successfully migrated 1 legacy files"
}
```

#### `check_migration_needed(container_manager, session_id, workspace_path="/workspace")`

Checks if migration is needed by:
1. Looking for the `.vibe_migration_complete` marker file
2. Searching for legacy files if marker doesn't exist

**Returns:** `True` if migration is needed, `False` otherwise

#### `mark_migration_complete(container_manager, session_id, workspace_path="/workspace")`

Creates a marker file to indicate migration has been completed.

**Returns:** `True` if successful, `False` otherwise

### Integration Points

The migration is integrated into:

1. **Container Creation** (`/api/vibecode/container/create`)
   - Runs after container is created
   - Checks existing volumes for legacy files

2. **Container Start** (`/api/vibecode/container/{session_id}/start`)
   - Runs when container is started
   - Ensures migration happens on first use

### API Response

When migration occurs, the API response includes migration information:

```json
{
    "session_id": "abc-123",
    "status": "running",
    "message": "Container started successfully",
    "migration": {
        "migrated_files": [...],
        "total_count": 3,
        "legacy_dir": "/workspace/vibe_legacy",
        "timestamp": "2025-01-07T10:30:00",
        "message": "Successfully migrated 3 legacy files"
    }
}
```

## User Experience

### What Users See

1. **First Session Open**: Migration happens automatically in the background
2. **Legacy Directory**: A new `vibe_legacy` folder appears in the file explorer
3. **README File**: Contains information about the migration
4. **Clean Workspace**: Original workspace is clean of legacy files

### Accessing Migrated Files

Users can:
- Browse the `vibe_legacy` directory in the file explorer
- Open and edit migrated files
- Move files back to the main workspace if needed
- Delete the legacy directory if no longer needed

## Testing

### Manual Testing

Use the provided test script:

```bash
cd aidev/python_back_end
python test_migration.py
```

The script will:
1. Create test legacy files
2. Run the migration
3. Verify files were moved correctly
4. Check that migration doesn't run twice

### Automated Testing

The migration is tested as part of the container lifecycle tests:

```bash
cd aidev/python_back_end
python -m pytest tests/ -k migration
```

## Troubleshooting

### Migration Doesn't Run

**Symptom**: Legacy files remain in workspace

**Solutions**:
1. Check if `.vibe_migration_complete` marker exists
2. Delete marker file to force re-migration: `rm /workspace/.vibe_migration_complete`
3. Check container logs for migration errors

### Files Not Detected

**Symptom**: Some legacy files weren't migrated

**Possible Causes**:
1. Files are in subdirectories deeper than 5 levels (increase `maxdepth` in find command)
2. Files don't match the detection pattern
3. Files have unusual permissions

**Solution**: Manually move files to `vibe_legacy` directory

### Migration Fails

**Symptom**: Error in API response or logs

**Common Issues**:
1. Container not running
2. Insufficient permissions
3. Disk space issues

**Solution**: Check container logs and ensure container has proper permissions

## Security Considerations

### Path Validation

The migration system:
- Only operates within `/workspace`
- Validates all paths to prevent directory traversal
- Skips symlinks that point outside workspace

### Resource Limits

Migration is designed to:
- Handle large numbers of files efficiently
- Use minimal memory
- Complete quickly (< 5 seconds for typical workspaces)

### Error Handling

If migration fails:
- Container creation/start still succeeds
- Error is logged but doesn't block user
- User can manually migrate files if needed

## Configuration

### Workspace Path

Default: `/workspace`

Can be customized by passing `workspace_path` parameter to migration functions.

### Search Depth

Default: 5 levels deep

Configured in the `find` command within `migrate_legacy_colab_files()`.

### File Patterns

Current patterns:
- `*colab*` (case-insensitive)
- `*.ipynb`

To add more patterns, modify the `find` command in `migration.py`.

## Future Enhancements

Potential improvements:
1. **UI Notification**: Show toast notification when migration occurs
2. **Migration Report**: Detailed report in UI showing what was migrated
3. **Selective Migration**: Allow users to choose which files to migrate
4. **Undo Migration**: Option to move files back to original locations
5. **Archive Option**: Compress legacy files into a zip archive

## Related Requirements

This feature satisfies requirements:
- **10.1**: Detect and migrate files with "colab" in name
- **10.2**: Remove "Google Colab" references from UI
- **10.3**: Use `/api/vibecode/*` naming convention
- **10.4**: Move legacy files to `vibe_legacy/` directory
- **10.5**: Use "Vibe" terminology consistently

## Changelog

### Version 1.0 (2025-01-07)
- Initial implementation
- Automatic detection and migration
- README generation
- Idempotent operation with marker file
- Integration with container lifecycle
