# Requirements Document

## Introduction

This feature implements a comprehensive web-based IDE with secure code execution capabilities and AI assistant integration. The IDE will provide a Monaco editor with syntax highlighting, code completion, and the ability to execute code in isolated Docker containers. Additionally, it will include an AI assistant with multiple model options for code assistance and completion.

## Requirements

### Requirement 1

**User Story:** As a developer, I want to write and execute Python code in a secure environment, so that I can test and run code without affecting my local system.

#### Acceptance Criteria

1. WHEN a user submits code via POST /api/run THEN the system SHALL create a temporary file with the code content
2. WHEN the temporary file is created THEN the system SHALL spin up a Docker container with python:3.11-slim image
3. WHEN the container is running THEN the system SHALL mount the temporary file and execute `python /code/main.py`
4. WHEN code execution completes THEN the system SHALL capture both stdout and stderr
5. WHEN execution is successful THEN the system SHALL return { output: string }
6. WHEN execution fails THEN the system SHALL return { error: string }
7. WHEN the execution is complete THEN the system SHALL clean up temporary files and containers

### Requirement 2

**User Story:** As a developer, I want to interact with an AI assistant for code help, so that I can get programming assistance and code suggestions.

#### Acceptance Criteria

1. WHEN a user sends messages via POST /api/assistant THEN the system SHALL accept a list of messages with role and content
2. WHEN the assistant endpoint is called THEN the system SHALL use subprocess to call `ollama run llama3.2:3b`
3. WHEN calling Ollama THEN the system SHALL pass the conversation messages via stdin
4. WHEN Ollama responds THEN the system SHALL capture and parse the stdout
5. WHEN the response is parsed THEN the system SHALL return { reply: string }
6. WHEN the assistant is processing THEN the system SHALL handle streaming responses appropriately

### Requirement 3

**User Story:** As a developer, I want to choose between different AI models for assistance, so that I can use the most appropriate model for my needs.

#### Acceptance Criteria

1. WHEN the AI assistant interface loads THEN the system SHALL display a toggle/dropdown for model selection
2. WHEN a user selects a different model THEN the system SHALL update the assistant configuration
3. WHEN making assistant requests THEN the system SHALL use the selected model for responses
4. WHEN switching models THEN the system SHALL maintain conversation context appropriately
5. IF a selected model is unavailable THEN the system SHALL fallback to a default model and notify the user

### Requirement 4

**User Story:** As a developer, I want a full-featured Monaco editor with syntax highlighting and code completion, so that I can write code efficiently with a professional IDE experience.

#### Acceptance Criteria

1. WHEN the IDE loads THEN the system SHALL initialize Monaco editor with the vibe-dark theme
2. WHEN typing code THEN the system SHALL provide syntax highlighting for multiple languages
3. WHEN requesting code completion THEN the system SHALL integrate AI-powered suggestions
4. WHEN using the editor THEN the system SHALL support features like auto-closing brackets, formatting, and minimap
5. WHEN working with files THEN the system SHALL support multiple file tabs and file management
6. WHEN saving files THEN the system SHALL persist changes and indicate modification status

### Requirement 5

**User Story:** As a developer, I want secure code execution with proper isolation, so that malicious or buggy code cannot harm the host system.

#### Acceptance Criteria

1. WHEN executing code THEN the system SHALL run all code in isolated Docker containers
2. WHEN creating containers THEN the system SHALL use resource limits to prevent resource exhaustion
3. WHEN code execution times out THEN the system SHALL terminate the container and return an error
4. WHEN containers finish execution THEN the system SHALL automatically clean up containers and temporary files
5. WHEN handling file operations THEN the system SHALL use secure temporary file creation
6. WHEN mounting files THEN the system SHALL use read-only mounts where appropriate

### Requirement 6

**User Story:** As a developer, I want proper error handling and user feedback, so that I can understand what went wrong when code execution or AI assistance fails.

#### Acceptance Criteria

1. WHEN Docker operations fail THEN the system SHALL return descriptive error messages
2. WHEN code execution fails THEN the system SHALL distinguish between compilation errors and runtime errors
3. WHEN AI assistant calls fail THEN the system SHALL provide fallback responses or error messages
4. WHEN network issues occur THEN the system SHALL handle timeouts gracefully
5. WHEN system resources are low THEN the system SHALL queue or reject requests appropriately
6. WHEN errors occur THEN the system SHALL log errors for debugging while returning user-friendly messages