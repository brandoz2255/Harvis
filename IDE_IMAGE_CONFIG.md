# IDE Image Configuration

## Environment Variable

Set `VIBECODING_IDE_IMAGE` to configure the Docker image used for IDE containers.

### Default
```bash
VIBECODING_IDE_IMAGE=ghcr.io/coder/code-server:latest
```

### Recommended Images

#### 1. GitHub Container Registry (Preferred)
```bash
# Latest stable release
VIBECODING_IDE_IMAGE=ghcr.io/coder/code-server:latest

# Specific version (recommended for production)
VIBECODING_IDE_IMAGE=ghcr.io/coder/code-server:4.104.3
```

#### 2. LinuxServer.io (Alternative)
```bash
# Latest from LinuxServer
VIBECODING_IDE_IMAGE=lscr.io/linuxserver/code-server:latest

# Specific version
VIBECODING_IDE_IMAGE=lscr.io/linuxserver/code-server:4.104.3
```

## Error Handling

The system includes automatic fallback logic:

1. **Primary Image**: Tries to pull the configured image
2. **Fallback**: If the primary image is `ghcr.io/coder/code-server:*` and fails, automatically tries `lscr.io/linuxserver/code-server:latest`
3. **Error Messages**: Clear error messages with suggested fixes

## Example Error Messages

### Image Not Found
```
IDE image not found or access denied: coder/code-server:4.92.0. 
Please set VIBECODING_IDE_IMAGE to a valid image like 
'ghcr.io/coder/code-server:4.104.3' or 'lscr.io/linuxserver/code-server:latest'
```

### Docker Pull Failed
```
Docker pull failed for both ghcr.io/coder/code-server:latest and lscr.io/linuxserver/code-server:latest. 
Please check VIBECODING_IDE_IMAGE environment variable.
```

## Docker Compose Example

```yaml
services:
  backend:
    environment:
      - VIBECODING_IDE_IMAGE=ghcr.io/coder/code-server:4.104.3
```

## Production Recommendations

1. **Pin to specific version** for reproducible builds
2. **Use GHCR images** for better performance and reliability
3. **Test image availability** before deployment
4. **Monitor Docker Hub rate limits** for CI/CD pipelines

## Troubleshooting

### Pull Access Denied
- Check if the image exists: `docker pull ghcr.io/coder/code-server:4.104.3`
- Verify network connectivity
- Check Docker Hub authentication if using private images

### Image Not Found
- Verify the image name and tag
- Check if the image is publicly available
- Try the fallback image manually: `docker pull lscr.io/linuxserver/code-server:latest`
