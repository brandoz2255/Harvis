"""
Artifact Executor Service - FastAPI app that runs inside executor pods

This service:
1. Receives build requests from the backend
2. Writes files to workspace
3. Runs npm install
4. Builds the Next.js app
5. Starts the app server
6. Reports status back to backend via callbacks
"""

import os
import sys
import json
import asyncio
import logging
import subprocess
import shutil
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
import aiohttp

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
from artifacts.executor_models import (
    BuildRequest,
    BuildStatusUpdate,
    BuildJobStatus,
    ExecutorHealth,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Configuration
WORKSPACE_DIR = Path(os.environ.get("EXECUTOR_WORKSPACE", "/workspace"))
ARTIFACTS_DIR = Path(os.environ.get("ARTIFACTS_DIR", "/data/artifacts"))
BACKEND_URL = os.environ.get("BACKEND_URL", "http://harvis-ai-backend:8000")
CALLBACK_TOKEN = os.environ.get("CALLBACK_TOKEN", "")
POD_NAME = os.environ.get("HOSTNAME", "unknown-pod")
NAMESPACE = os.environ.get("POD_NAMESPACE", "artifact-executor")
NODE_NAME = os.environ.get("NODE_NAME", "unknown-node")

# Track running builds
_running_builds: Dict[str, Dict[str, Any]] = {}
_build_tasks: Dict[str, asyncio.Task] = {}


async def send_status_update(update: BuildStatusUpdate):
    """Send status update to backend"""
    try:
        async with aiohttp.ClientSession() as session:
            headers = {"Content-Type": "application/json"}
            if CALLBACK_TOKEN:
                headers["Authorization"] = f"Bearer {CALLBACK_TOKEN}"

            url = f"{BACKEND_URL}/api/artifacts/build-status"
            async with session.post(
                url,
                json=update.model_dump(mode="json"),
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as response:
                if response.status != 200:
                    logger.error(f"Failed to send status update: {response.status}")
                else:
                    logger.debug(f"Status update sent for job {update.job_id}")
    except Exception as e:
        logger.error(f"Error sending status update: {e}")


async def write_files(files: Dict[str, str], workspace: Path):
    """Write source files to workspace"""
    for filepath, content in files.items():
        # Normalize path (remove leading slash)
        filepath = filepath.lstrip("/")
        full_path = workspace / filepath

        # Create parent directories
        full_path.parent.mkdir(parents=True, exist_ok=True)

        # Write file
        full_path.write_text(content, encoding="utf-8")
        logger.info(f"Written file: {full_path}")


async def create_package_json(
    workspace: Path, dependencies: Dict[str, str], framework: str, entry_file: str
):
    """Create package.json for the project"""
    if framework == "nextjs":
        package = {
            "name": "artifact-app",
            "version": "1.0.0",
            "private": True,
            "scripts": {
                "dev": "next dev",
                "build": "next build",
                "start": "next start",
            },
            "dependencies": {
                "next": "^14.0.0",
                "react": "^18.2.0",
                "react-dom": "^18.2.0",
                "typescript": "^5.0.0",
                "@types/node": "^20.0.0",
                "@types/react": "^18.2.0",
                "@types/react-dom": "^18.2.0",
                **dependencies,
            },
        }
    elif framework == "react":
        package = {
            "name": "artifact-app",
            "version": "1.0.0",
            "private": True,
            "scripts": {
                "dev": "vite",
                "build": "vite build",
                "preview": "vite preview",
            },
            "dependencies": {
                "react": "^18.2.0",
                "react-dom": "^18.2.0",
                **dependencies,
            },
            "devDependencies": {
                "@types/react": "^18.2.0",
                "@types/react-dom": "^18.2.0",
                "@vitejs/plugin-react": "^4.0.0",
                "typescript": "^5.0.0",
                "vite": "^5.0.0",
            },
        }
    else:
        package = {
            "name": "artifact-app",
            "version": "1.0.0",
            "private": True,
            "scripts": {"start": "node index.js"},
            "dependencies": dependencies,
        }

    package_path = workspace / "package.json"
    package_path.write_text(json.dumps(package, indent=2))
    logger.info(f"Created package.json at {package_path}")


async def create_nextjs_config(workspace: Path, port: int):
    """Create next.config.js for Next.js apps"""
    config = f"""/** @type {{import('next').NextConfig}} */
const nextConfig = {{
  output: 'standalone',
  distDir: 'dist',
  experimental: {{
    appDir: false,
  }},
}}

module.exports = nextConfig
"""
    config_path = workspace / "next.config.js"
    config_path.write_text(config)
    logger.info(f"Created next.config.js")


def run_command(
    cmd: list, cwd: Path, env: Optional[Dict[str, str]] = None
) -> subprocess.CompletedProcess:
    """Run a shell command and capture output"""
    env_vars = {**os.environ, **(env or {})}

    logger.info(f"Running command: {' '.join(cmd)} in {cwd}")

    result = subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        env=env_vars,
        timeout=300,  # 5 minute timeout
    )

    if result.returncode != 0:
        logger.error(f"Command failed: {result.stderr}")
        raise subprocess.CalledProcessError(
            result.returncode, cmd, output=result.stdout, stderr=result.stderr
        )

    logger.info(f"Command succeeded")
    return result


async def build_artifact(request: BuildRequest, workspace: Path, build_logs: list):
    """Build the artifact"""
    try:
        # Write source files
        build_logs.append("[PHASE] Writing source files...")
        await write_files(request.files, workspace)

        # Create package.json
        build_logs.append("[PHASE] Creating package.json...")
        await create_package_json(
            workspace, request.dependencies, request.framework, request.entry_file
        )

        # Create Next.js config if needed
        if request.framework == "nextjs":
            await create_nextjs_config(workspace, request.port)

        # Install dependencies
        build_logs.append("[PHASE] Installing dependencies...")
        result = await asyncio.to_thread(run_command, ["npm", "install"], workspace)
        build_logs.append(result.stdout)
        if result.stderr:
            build_logs.append(f"[STDERR] {result.stderr}")

        # Build the app
        build_logs.append("[PHASE] Building application...")
        result = await asyncio.to_thread(
            run_command, ["npm", "run", "build"], workspace
        )
        build_logs.append(result.stdout)
        if result.stderr:
            build_logs.append(f"[STDERR] {result.stderr}")

        # Copy build output to artifacts directory
        build_logs.append("[PHASE] Copying build output...")
        output_dir = Path(request.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        if request.framework == "nextjs":
            dist_dir = workspace / "dist"
            if dist_dir.exists():
                shutil.copytree(dist_dir, output_dir, dirs_exist_ok=True)
        else:
            # For other frameworks, copy all files
            for item in workspace.iterdir():
                if item.is_dir():
                    shutil.copytree(item, output_dir / item.name, dirs_exist_ok=True)
                else:
                    shutil.copy2(item, output_dir / item.name)

        build_logs.append("[SUCCESS] Build completed successfully")
        return True

    except subprocess.CalledProcessError as e:
        build_logs.append(f"[ERROR] Build failed: {e}")
        build_logs.append(f"[STDOUT] {e.output}")
        build_logs.append(f"[STDERR] {e.stderr}")
        raise
    except Exception as e:
        build_logs.append(f"[ERROR] Unexpected error: {e}")
        raise


async def run_artifact(
    request: BuildRequest, workspace: Path, build_logs: list
) -> subprocess.Popen:
    """Start the artifact server"""
    try:
        build_logs.append("[PHASE] Starting application server...")

        # Set port environment variable
        env = {**os.environ, "PORT": str(request.port)}

        # Start the server
        if request.framework == "nextjs":
            cmd = ["npm", "start"]
        else:
            cmd = ["npm", "start"]

        process = subprocess.Popen(
            cmd,
            cwd=workspace,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        build_logs.append(
            f"[SUCCESS] Server started on port {request.port} (PID: {process.pid})"
        )
        return process

    except Exception as e:
        build_logs.append(f"[ERROR] Failed to start server: {e}")
        raise


async def process_build(request: BuildRequest):
    """Process a build request"""
    job_id = str(request.job_id)
    build_logs = []
    process = None

    try:
        # Create workspace
        workspace = WORKSPACE_DIR / job_id
        workspace.mkdir(parents=True, exist_ok=True)

        logger.info(f"Starting build for job {job_id}")

        # Update status to building
        await send_status_update(
            BuildStatusUpdate(
                job_id=request.job_id,
                artifact_id=request.artifact_id,
                status=BuildJobStatus.BUILDING,
                progress_percentage=10,
                current_phase="installing",
                pod_name=POD_NAME,
                namespace=NAMESPACE,
                node_name=NODE_NAME,
                started_at=datetime.utcnow(),
            )
        )

        # Build the artifact
        await build_artifact(request, workspace, build_logs)

        # Update status to built
        await send_status_update(
            BuildStatusUpdate(
                job_id=request.job_id,
                artifact_id=request.artifact_id,
                status=BuildJobStatus.BUILDING,
                progress_percentage=80,
                current_phase="starting",
                pod_name=POD_NAME,
                namespace=NAMESPACE,
                node_name=NODE_NAME,
                built_at=datetime.utcnow(),
                build_logs="\n".join(build_logs),
            )
        )

        # Start the server
        process = await run_artifact(request, workspace, build_logs)

        # Store process info
        _running_builds[job_id] = {
            "process": process,
            "port": request.port,
            "workspace": workspace,
            "start_time": datetime.utcnow(),
        }

        # Wait a moment for server to start
        await asyncio.sleep(5)

        # Update status to running
        preview_url = f"http://localhost:{request.port}"
        await send_status_update(
            BuildStatusUpdate(
                job_id=request.job_id,
                artifact_id=request.artifact_id,
                status=BuildJobStatus.RUNNING,
                progress_percentage=100,
                current_phase="running",
                preview_url=preview_url,
                pod_name=POD_NAME,
                namespace=NAMESPACE,
                node_name=NODE_NAME,
                running_at=datetime.utcnow(),
                build_logs="\n".join(build_logs),
            )
        )

        logger.info(f"Job {job_id} is now running at {preview_url}")

        # Monitor the process
        while process.poll() is None:
            await asyncio.sleep(10)

            # Send heartbeat
            await send_status_update(
                BuildStatusUpdate(
                    job_id=request.job_id,
                    artifact_id=request.artifact_id,
                    status=BuildJobStatus.RUNNING,
                    progress_percentage=100,
                    current_phase="running",
                    preview_url=preview_url,
                    pod_name=POD_NAME,
                    namespace=NAMESPACE,
                    node_name=NODE_NAME,
                )
            )

        # Process exited
        build_logs.append(f"[INFO] Server exited with code {process.returncode}")

        await send_status_update(
            BuildStatusUpdate(
                job_id=request.job_id,
                artifact_id=request.artifact_id,
                status=BuildJobStatus.STOPPED,
                progress_percentage=100,
                build_logs="\n".join(build_logs),
                completed_at=datetime.utcnow(),
            )
        )

    except Exception as e:
        logger.error(f"Build failed for job {job_id}: {e}")
        build_logs.append(f"[ERROR] {str(e)}")

        await send_status_update(
            BuildStatusUpdate(
                job_id=request.job_id,
                artifact_id=request.artifact_id,
                status=BuildJobStatus.FAILED,
                error_message=str(e),
                build_logs="\n".join(build_logs),
                completed_at=datetime.utcnow(),
            )
        )

    finally:
        # Cleanup
        if job_id in _running_builds:
            del _running_builds[job_id]
        if job_id in _build_tasks:
            del _build_tasks[job_id]


# FastAPI app
@asynccontextmanager
async def lifespan(app: FastAPI):
    """App lifespan manager"""
    logger.info("Executor service starting...")

    # Create directories
    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

    yield

    # Cleanup on shutdown
    logger.info("Executor service shutting down...")
    for job_id, info in _running_builds.items():
        if info.get("process"):
            info["process"].terminate()


app = FastAPI(
    title="Harvis Artifact Executor",
    description="Isolated code execution service for artifact builds",
    version="1.0.0",
    lifespan=lifespan,
)


@app.post("/build")
async def start_build(request: BuildRequest, background_tasks: BackgroundTasks):
    """Start a new build"""
    job_id = str(request.job_id)

    if job_id in _build_tasks:
        raise HTTPException(status_code=409, detail="Build already in progress")

    # Start build in background
    task = asyncio.create_task(process_build(request))
    _build_tasks[job_id] = task

    return JSONResponse(
        {"status": "accepted", "job_id": job_id, "message": "Build started"}
    )


@app.post("/stop/{job_id}")
async def stop_build(job_id: str):
    """Stop a running build"""
    if job_id not in _running_builds:
        raise HTTPException(status_code=404, detail="Build not found")

    info = _running_builds[job_id]
    process = info.get("process")

    if process:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()

    # Cancel task
    if job_id in _build_tasks:
        _build_tasks[job_id].cancel()

    return JSONResponse({"status": "stopped", "job_id": job_id})


@app.get("/status/{job_id}")
async def get_status(job_id: str):
    """Get build status"""
    if job_id not in _running_builds:
        return JSONResponse({"status": "not_found", "job_id": job_id})

    info = _running_builds[job_id]
    process = info.get("process")

    return JSONResponse(
        {
            "status": "running" if process and process.poll() is None else "stopped",
            "job_id": job_id,
            "port": info.get("port"),
            "uptime_seconds": (datetime.utcnow() - info["start_time"]).total_seconds(),
        }
    )


@app.get("/logs/{job_id}")
async def get_logs(job_id: str, tail: int = 100):
    """Get build logs"""
    # TODO: Implement log retrieval
    return JSONResponse(
        {"job_id": job_id, "logs": ["Log retrieval not yet implemented"]}
    )


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return JSONResponse(
        {
            "status": "healthy",
            "pod": POD_NAME,
            "namespace": NAMESPACE,
            "node": NODE_NAME,
            "running_builds": len(_running_builds),
            "timestamp": datetime.utcnow().isoformat(),
        }
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8080)
