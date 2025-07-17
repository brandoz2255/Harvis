"""
n8n Automation Module

This module provides functionality to programmatically create and manage n8n workflows
via the n8n REST API. It integrates with the Jarvis AI chatbot to enable natural language
workflow creation.
"""

from .client import N8nClient
from .workflow_builder import WorkflowBuilder, WorkflowTemplate
from .automation_service import N8nAutomationService
from .storage import N8nStorage
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