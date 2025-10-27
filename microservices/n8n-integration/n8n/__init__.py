"""
n8n Automation Module

This module provides functionality to programmatically create and manage n8n workflows
via the n8n REST API. It integrates with the Jarvis AI chatbot to enable natural language
workflow creation with vector database enhanced AI agents.
"""

from .client import N8nClient
from .workflow_builder import WorkflowBuilder, WorkflowTemplate
from .automation_service import N8nAutomationService
from .storage import N8nStorage
from .vector_db import VectorDatabaseService, get_vector_db_service, initialize_vector_db
from .ai_agent import N8nAIAgent, get_ai_agent, initialize_ai_agent
from .models import (
    WorkflowConfig, WorkflowNode, WorkflowConnection, 
    CreateWorkflowRequest, N8nAutomationRequest, WorkflowExecutionRequest,
    WorkflowResponse, WorkflowRecord, AutomationHistory
)

__all__ = [
    'N8nClient',
    'WorkflowBuilder', 
    'WorkflowTemplate',
    'N8nAutomationService',
    'N8nStorage',
    'VectorDatabaseService',
    'get_vector_db_service',
    'initialize_vector_db',
    'N8nAIAgent',
    'get_ai_agent',
    'initialize_ai_agent',
    'WorkflowConfig',
    'WorkflowNode',
    'WorkflowConnection',
    'CreateWorkflowRequest',
    'N8nAutomationRequest',
    'WorkflowExecutionRequest',
    'WorkflowResponse',
    'WorkflowRecord',
    'AutomationHistory'
]