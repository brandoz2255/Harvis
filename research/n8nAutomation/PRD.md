Product Requirements Document (PRD)
Project: AI-Driven n8n Workflow Automation via Python Backend
1. Purpose

Enable an AI-powered chatbot (integrated into your Python backend) to programmatically create and manage n8n workflows by interacting with the n8n REST API. The overall system should be containerized and leverage your existing PostgreSQL database for enhanced metadata storage.
2. Objectives

    Seamlessly allow non-technical users to generate and manage automated workflows in n8n by conversing with the AI chatbot.

    Ensure secure, robust, and scalable integration between the chatbot, n8n, and PostgreSQL.

    Provide a maintainable, extensible backend suited for further AI and workflow enhancements.

3. System Overview
Component	Description
n8n Self-Hosted	Workflow automation tool running in Docker container with exposed REST API
Python Backend	Hosts the AI chatbot, interfaces with users, manages workflow creation via n8n’s API
PostgreSQL	Stores workflow templates, histories, user prompts, and metadata
Docker Network	Ensures secure, fast inter-container communication
4. Functional Requirements
4.1. AI Chatbot User Interface

    Handles user requests to describe desired automations in natural language.

    Parses intent and translates to workflow actions.

4.2. Backend Logic

    Receives user input from chatbot, interprets with AI, models desired workflow as n8n workflow JSON.

    Authenticates and communicates with n8n REST API for workflow CRUD operations.

    Stores/retrieves relevant data (workflow templates, history, prompts) within PostgreSQL.

    Exposes REST API endpoints (e.g., /create-n8n-workflow) to initiate workflow creation.

4.3. Workflow Creation & Management

    Composes valid n8n workflow JSON with details such as node types, connections, and parameters.

    Supports all basic n8n nodes (Start, HTTP Request, etc.); extensibility for more in future.

    Handles error responses from n8n and provides meaningful feedback to users.

4.4. Security & Deployment

    n8n authenticates requests using Basic Auth or equivalent.

    All inter-service traffic stays within Docker network.

    n8n container’s data folder persisted to avoid data loss.

    FastAPI (or Flask) and n8n log errors and events for observability.

5. Non-Functional Requirements

    Reliability: Workflows persist across container/application restarts.

    Scalability: Must support concurrent chat sessions and workflow automations.

    Security: Enforce authentication for all internal and external APIs. No sensitive secrets hard-coded.

    Usability: Chatbot responses must be clear, actionable, and informative.

6. Technical Stack
Component	Technology	Purpose
Workflow Engine	n8n (Docker)	Automating workflows
Backend/API	Python (FastAPI)	Chatbot & business logic
REST Calls	requests (Python)	Communicate with n8n API
Data Modeling	pydantic	Validate workflow input
DB ORM	SQLAlchemy	PostgreSQL integration
Relational Store	PostgreSQL	Store workflows/templates
Containerization	Docker, Compose	Service orchestration
7. Sample Workflow Creation Flow

    User Input: User instructs chatbot (“Create a workflow that fetches weather info daily.”)

    AI Backend: Chatbot parses intent, creates workflow JSON:

        Start node (schedule trigger)

        HTTP Request node (GET to weather API)

        Data transformation (if needed)

    REST API Call: Backend uses authenticated request to POST workflow to n8n REST API.

    Workflow Persistence: Response ID, structure, and metadata stored in PostgreSQL.

    Confirmation: User receives confirmation and, optionally, a summary or link to the new workflow.

8. Example API Interaction (Python)

python
import requests
from requests.auth import HTTPBasicAuth

N8N_URL = "http://n8n:5678/rest/workflows"
N8N_USER = "yourUser"
N8N_PASS = "yourPassword"

def create_n8n_workflow(workflow_json):
    resp = requests.post(
        N8N_URL,
        json=workflow_json,
        auth=HTTPBasicAuth(N8N_USER, N8N_PASS)
    )
    resp.raise_for_status()
    return resp.json()

9. Docker Compose Excerpt

text
services:
  n8n:
    image: n8nio/n8n:latest
    ports:
      - "5678:5678"
    environment:
      - N8N_BASIC_AUTH_ACTIVE=true
      - N8N_BASIC_AUTH_USER=yourUser
      - N8N_BASIC_AUTH_PASSWORD=yourPassword
    volumes:
      - ./n8n_data:/home/node/.n8n
    networks:
      - your-docker-network

  backend:
    build: ./backend
    environment:
      - DATABASE_URL=postgresql://user:pass@postgres/db
    networks:
      - your-docker-network

  postgres:
    image: postgres:latest
    networks:
      - your-docker-network

networks:
  your-docker-network:
    external: true

10. Acceptance Criteria

    User can request workflow creation via chatbot; corresponding workflow appears in n8n GUI.

    Workflows are persistent and recoverable after service restarts.

    All user API calls are authenticated and rate-limited if needed.

    PostgreSQL contains audit trail of workflow creation and associated prompts/intents.

    Informative error retries/feedback are present for failed creations.

11. Future Extensions

    Add user authentication/authorization for chatbot access.

    Expand workflow template library in DB for common requests.

    Enable n8n to trigger back into backend/DB (webhook nodes, etc.).

    Support more node types and custom code execution if required.

This PRD outlines all foundational features, requirements, and architecture to implement your AI-driven n8n workflow automation system within a containerized, secure Python environment.
