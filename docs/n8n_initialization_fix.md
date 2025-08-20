# Fixing the n8n Service Initialization Issue

This document explains how to fix the `503 Service Unavailable` error for the `/api/n8n/ai-automate` endpoint.

## The Problem

The error occurs because the `n8n_ai_agent`, which is required by the `/api/n8n/ai-automate` endpoint, is not being initialized when the application starts.

In `python_back_end/main.py`, the initialization logic is inside a function called `startup_event_disabled`. However, the `@app.on_event("startup")` decorator that would normally trigger this function is commented out. Instead, the application uses a `lifespan` context manager for startup and shutdown events, but this `lifespan` manager does not include the necessary n8n initialization code.

As a result, `n8n_ai_agent` remains `None`, and any call to the endpoint that depends on it fails with a 503 error.

## The Solution

The fix involves moving the n8n service initialization logic from the `startup_event_disabled` function into the `lifespan` function and then removing the now-redundant code.

### Step 1: Locate `python_back_end/main.py`

Open the file `python_back_end/main.py` in your editor.

### Step 2: Replace the `lifespan` function and remove the old startup logic

You will replace a large block of code that includes the current `lifespan` function and the unused `startup_event_disabled` and `shutdown_event` functions with a single, corrected `lifespan` function.

**Find and delete the following block of code (approximately from line 258 to 450):**

```python
# ─── Database Connection Pool -------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: create connection pool
    try:
        # Fix database hostname: use pgsql-db instead of pgsql
        database_url = os.getenv("DATABASE_URL", "postgresql://pguser:pgpassword@pgsql-db:5432/database")
        app.state.pg_pool = await asyncpg.create_pool(
            dsn=database_url,
            min_size=1, 
            max_size=10,
            command_timeout=30,  # Increased from 5 to 30 seconds
        )
        logger.info("✅ Database connection pool created")
        
        # Initialize session database
        from vibecoding.db_session import init_session_db
        await init_session_db(app.state.pg_pool)
        
        # Initialize chat history manager
        global chat_history_manager
        chat_history_manager = ChatHistoryManager(app.state.pg_pool)
        logger.info("✅ ChatHistoryManager initialized in lifespan")
        
        # Initialize vibe files database table
        try:
            from vibecoding.files import ensure_vibe_files_table
            await ensure_vibe_files_table()
            logger.info("✅ Vibe files database table initialized")
        except Exception as e:
            logger.error(f"❌ Failed to initialize vibe files table: {e}")
        
    except Exception as e:
        logger.error(f"❌ Failed to create database pool: {e}")
        # Continue without pool - will fall back to direct connections
        app.state.pg_pool = None
    
    yield
    
    # Shutdown: close connection pool
    if hasattr(app.state, 'pg_pool') and app.state.pg_pool:
        await app.state.pg_pool.close()
        logger.info("🔒 Database connection pool closed")

# ─── FastAPI init --------------------------------------------------------------
app = FastAPI(title="Harvis AI API", lifespan=lifespan)

# ... (keep the middleware and router includes)

# ─── Database Pool and Chat History Manager Init ─────────────────────────────────────────────────
db_pool = None
chat_history_manager = None

# @app.on_event("startup")  # Disabled - using lifespan instead
async def startup_event_disabled():
    global db_pool, chat_history_manager, n8n_storage, n8n_automation_service, n8n_ai_agent
    try:
        logger.info("🚀 Starting startup event initialization...")
        
        # Use the connection pool created in lifespan
        db_pool = app.state.pg_pool
        if db_pool is None:
            logger.error("❌ No database pool available - falling back to direct connection")
            # Fix database hostname: use pgsql-db instead of pgsql
            database_url = os.getenv("DATABASE_URL", "postgresql://pguser:pgpassword@pgsql-db:5432/database")
            db_pool = await asyncpg.create_pool(database_url)
        else:
            logger.info("✅ Using database pool from lifespan")
        
        logger.info("🔄 Initializing ChatHistoryManager...")
        chat_history_manager = ChatHistoryManager(db_pool)
        logger.info("✅ ChatHistoryManager initialized successfully")
        
        # Initialize vibe files database table
        try:
            from vibecoding.files import ensure_vibe_files_table
            await ensure_vibe_files_table()
            logger.info("✅ Vibe files database table initialized")
        except Exception as e:
            logger.error(f"❌ Failed to initialize vibe files table: {e}")
        
        # Session database already initialized in lifespan
        logger.info("📋 Using session database initialized in lifespan")
        
        # Initialize n8n services with database pool
        if n8n_client:
            n8n_storage = N8nStorage(db_pool)
            await n8n_storage.ensure_tables()
            
            workflow_builder = WorkflowBuilder()
            n8n_automation_service = N8nAutomationService(
                n8n_client=n8n_client,
                workflow_builder=workflow_builder,
                storage=n8n_storage,
                ollama_url=OLLAMA_URL
            )
            logger.info("✅ n8n automation service fully initialized")
            
            # Initialize AI agent with vector database
            try:
                from n8n import initialize_ai_agent
                n8n_ai_agent = await initialize_ai_agent(n8n_automation_service)
                logger.info("✅ n8n AI agent with vector database initialized")
            except Exception as e:
                logger.warning(f"⚠️ Failed to initialize n8n AI agent: {e}")
                logger.warning("n8n automation will work without vector database enhancement")
        
        logger.info("Database pool and all services initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize services: {e}")
        raise

@app.on_event("shutdown")
async def shutdown_event():
    global db_pool
    if db_pool:
        await db_pool.close()
        logger.info("Database pool closed")
```

**In its place, add the following corrected code:**

```python
# ─── Database Connection Pool -------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: create connection pool
    global db_pool, chat_history_manager, n8n_storage, n8n_automation_service, n8n_ai_agent
    try:
        # Fix database hostname: use pgsql-db instead of pgsql
        database_url = os.getenv("DATABASE_URL", "postgresql://pguser:pgpassword@pgsql-db:5432/database")
        app.state.pg_pool = await asyncpg.create_pool(
            dsn=database_url,
            min_size=1, 
            max_size=10,
            command_timeout=30,  # Increased from 5 to 30 seconds
        )
        db_pool = app.state.pg_pool
        logger.info("✅ Database connection pool created")
        
        # Initialize session database
        from vibecoding.db_session import init_session_db
        await init_session_db(app.state.pg_pool)
        
        # Initialize chat history manager
        chat_history_manager = ChatHistoryManager(app.state.pg_pool)
        logger.info("✅ ChatHistoryManager initialized in lifespan")
        
        # Initialize vibe files database table
        try:
            from vibecoding.files import ensure_vibe_files_table
            await ensure_vibe_files_table()
            logger.info("✅ Vibe files database table initialized")
        except Exception as e:
            logger.error(f"❌ Failed to initialize vibe files table: {e}")

        # Initialize n8n services with database pool
        if n8n_client:
            n8n_storage = N8nStorage(db_pool)
            await n8n_storage.ensure_tables()
            
            workflow_builder = WorkflowBuilder()
            n8n_automation_service = N8nAutomationService(
                n8n_client=n8n_client,
                workflow_builder=workflow_builder,
                storage=n8n_storage,
                ollama_url=OLLAMA_URL
            )
            logger.info("✅ n8n automation service fully initialized")
            
            # Initialize AI agent with vector database
            try:
                from n8n import initialize_ai_agent
                n8n_ai_agent = await initialize_ai_agent(n8n_automation_service)
                logger.info("✅ n8n AI agent with vector database initialized")
            except Exception as e:
                logger.warning(f"⚠️ Failed to initialize n8n AI agent: {e}")
                logger.warning("n8n automation will work without vector database enhancement")
        
        logger.info("Database pool and all services initialized successfully")
        
    except Exception as e:
        logger.error(f"❌ Failed to create database pool or initialize n8n services: {e}")
        # Continue without pool - will fall back to direct connections
        app.state.pg_pool = None
    
    yield
    
    # Shutdown: close connection pool
    if hasattr(app.state, 'pg_pool') and app.state.pg_pool:
        await app.state.pg_pool.close()
        logger.info("🔒 Database connection pool closed")

# ─── FastAPI init --------------------------------------------------------------
app = FastAPI(title="Harvis AI API", lifespan=lifespan)

# ... (keep the middleware and router includes)

# ─── Database Pool and Chat History Manager Init ─────────────────────────────────────────────────
db_pool = None
chat_history_manager = None

@app.on_event("shutdown")
async def shutdown_event():
    global db_pool
    if db_pool:
        await db_pool.close()
        logger.info("Database pool closed")
```

### Step 3: Restart the Application

After saving the changes to `python_back_end/main.py`, restart your backend service. The `n8n_ai_agent` will now be initialized correctly during startup, and the 503 error should be resolved.

## Phase Two: Fixing the Database Vector Extension

After applying the fix above, you may encounter a new error in the logs related to the database.

### The Problem

The logs show the following error:
```
ERROR:embedding_manager:Error searching workflows with scores: (psycopg2.errors.UndefinedFile) could not access file "$libdir/vector": No such file or directory
```
This error means that the PostgreSQL database is missing the `pgvector` extension, which is required for performing vector similarity searches (used by the AI to find similar workflows). The application is trying to use the `<=>` operator, which is specific to `pgvector`.

The cause is that the `pgsql` service in your `docker-compose.yaml` file is using the standard `postgres:15` image, which does not include this extension.

### The Solution

The solution is to update your `docker-compose.yaml` to use a Docker image that includes the `pgvector` extension and to ensure the extension is enabled in the database.

#### Step 1: Modify `docker-compose.yaml`

Open the `docker-compose.yaml` file in your editor.

Find the `pgsql` service definition:
```yaml
  pgsql:
    image: postgres:15
    container_name: pgsql-db
    restart: unless-stopped
    environment:
      POSTGRES_USER: pguser
      POSTGRES_PASSWORD: pgpassword
      POSTGRES_DB: database
    volumes:
      - pgsql_data:/var/lib/postgresql/data
    networks:
      - ollama-n8n-network
```

Modify it to look like this:
```yaml
  pgsql:
    image: pgvector/pgvector:pg15
    container_name: pgsql-db
    restart: unless-stopped
    environment:
      POSTGRES_USER: pguser
      POSTGRES_PASSWORD: pgpassword
      POSTGRES_DB: database
      POSTGRES_INITDB_ARGS: "-E UTF8 --locale=C"
    volumes:
      - pgsql_data:/var/lib/postgresql/data
      - ./init-db.sh:/docker-entrypoint-initdb.d/init-db.sh
    networks:
      - ollama-n8n-network
```
**Changes:**
1.  The `image` is changed from `postgres:15` to `pgvector/pgvector:pg15`.
2.  An `init-db.sh` script is mounted into the container to create the `vector` extension.

#### Step 2: Create the `init-db.sh` script

Create a new file named `init-db.sh` in the same directory as your `docker-compose.yaml` and add the following content:

```bash
#!/bin/bash
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE EXTENSION IF NOT EXISTS vector;
EOSQL
```

Make sure this script is executable by running:
```sh
chmod +x init-db.sh
```

#### Step 3: Restart the Docker Compose services

After saving the changes, you need to stop and restart your services for the changes to take effect. It's also a good idea to remove the old database volume to ensure a clean start with the new extension.

**Warning:** This will delete your existing database data.

Run the following commands:
```sh
docker-compose down
docker volume rm aidev_pgsql_data
docker-compose up -d
```

This will recreate the `pgsql` service with the `pgvector` extension enabled, which should resolve the database error.

## Phase Three: Manually Reinstalling the `pgvector` Extension (Corrected for Alpine Linux)

The commands in the previous version of this guide failed because the `pgvector/pgvector:pg15` Docker image is based on Alpine Linux, which uses the `apk` package manager, not `apt-get`.

If you find that the `pgvector` extension is missing, here are the corrected commands to run inside the container.

**Note:** This is a temporary fix. The underlying issue is likely related to your Docker environment or volume management, which should be investigated for a permanent solution.

### Step 1: Access the Database Container

First, open a shell inside your running `pgsql-db` container:

```sh
docker exec -it pgsql-db bash
```

### Step 2: Reinstall `pgvector` from Source

Since the `pgvector` package may not be available in the default repositories and the base image should already have it, building from source is the most reliable method if the files have been removed for some reason.

```sh
# The container runs as the 'postgres' user. You may need to switch to root to install packages.
# su -

# Update package lists and install necessary tools for building
apk update
apk add git build-base postgresql-dev

# Clone the pgvector repository
git clone --branch v0.7.2 https://github.com/pgvector/pgvector.git
cd pgvector

# Compile and install the extension
make
make install

# If you switched to the root user, switch back to the postgres user
# exit
```

### Step 3: Restart PostgreSQL and Verify

After installing the extension, you need to restart the PostgreSQL server for it to recognize the new files. The easiest way to do this is to exit the container and restart it with Docker Compose.

1.  **Exit the container shell:**
    ```sh
    exit
    ```

2.  **Restart the container:**
    ```sh
    docker-compose restart pgsql
    ```

These corrected commands use `apk` and should work within the `pgvector/pgvector:pg15` container environment.
