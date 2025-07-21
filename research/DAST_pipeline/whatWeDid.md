The updated workflow now properly handles your multi-container architecture with these key changes:
Key Adjustments for Your Setup:

Database Initialization:

Automatically runs your SQL setup scripts (db_setup.sql and chat_history_schema.sql)
Ensures database is ready before starting other services


Proper Network Configuration:

Uses your ollama-n8n-network to match your docker-compose setup
All containers communicate through the same network


Nginx Proxy Integration:

Mounts your nginx.conf from the repository
Scans through the proxy on port 9000 (matching your configuration)
Also performs direct backend scans for API testing


Multiple Scan Approaches:

Through Proxy: Tests the full application as users would access it
Direct Backend: Tests API endpoints directly for deeper vulnerability detection
Database Security: Includes SQL injection testing through application


Service Dependencies:

Ensures services start in the correct order
Proper health checks for each container
Waits for services to be fully ready before scanning



Additional Considerations:

Environment Variables: You may need to add more environment variables for your backend/frontend containers. Check your Dockerfiles for required configs.
Authentication: If your application requires authentication, you'll need to:

