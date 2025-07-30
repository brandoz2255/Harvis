"""
n8n Workflow Models

Pydantic models for n8n workflow configuration, validation, and database storage.
"""

from typing import Dict, List, Optional, Any, Union
from pydantic import BaseModel, Field, validator
from datetime import datetime
from enum import Enum


class NodeType(str, Enum):
    """Common n8n node types"""
    START = "n8n-nodes-base.start"
    MANUAL_TRIGGER = "n8n-nodes-base.manualTrigger"
    SCHEDULE_TRIGGER = "n8n-nodes-base.scheduleTrigger"
    WEBHOOK = "n8n-nodes-base.webhook"
    HTTP_REQUEST = "n8n-nodes-base.httpRequest"
    EMAIL = "n8n-nodes-base.emailSend"
    SLACK = "n8n-nodes-base.slack"
    DISCORD = "n8n-nodes-base.discord"
    CODE = "n8n-nodes-base.code"
    FUNCTION = "n8n-nodes-base.function"
    IF = "n8n-nodes-base.if"
    SWITCH = "n8n-nodes-base.switch"
    SET = "n8n-nodes-base.set"
    MERGE = "n8n-nodes-base.merge"
    SPLIT_IN_BATCHES = "n8n-nodes-base.splitInBatches"
    
    # LangChain nodes
    LANGCHAIN_AGENT = "@n8n/n8n-nodes-langchain.agent"
    LANGCHAIN_OPENAI = "@n8n/n8n-nodes-langchain.openAi"
    LANGCHAIN_OLLAMA = "@n8n/n8n-nodes-langchain.lmOllama"
    LANGCHAIN_CHAIN = "@n8n/n8n-nodes-langchain.chainLlm"
    LANGCHAIN_TOOL = "@n8n/n8n-nodes-langchain.toolAgent"
    
    # Additional common nodes
    YOUTUBE = "n8n-nodes-base.youTube"
    GOOGLE_SHEETS = "n8n-nodes-base.googleSheets"
    TWITTER = "n8n-nodes-base.twitter"
    TRELLO = "n8n-nodes-base.trello"
    NOTION = "n8n-nodes-base.notion"
    STICKY_NOTE = "n8n-nodes-base.stickyNote"


class WorkflowConnection(BaseModel):
    """n8n workflow connection between nodes"""
    node: str = Field(..., description="Target node name")
    type: str = Field(default="main", description="Connection type")
    index: int = Field(default=0, description="Connection index")


class WorkflowNode(BaseModel):
    """n8n workflow node configuration"""
    name: str = Field(..., description="Node name")
    type: str = Field(..., description="Node type (e.g., n8n-nodes-base.httpRequest)")
    typeVersion: int = Field(default=1, description="Node type version")
    position: List[int] = Field(default=[100, 100], description="Node position [x, y]")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Node parameters")
    credentials: Dict[str, str] = Field(default_factory=dict, description="Node credentials")
    
    @validator('position')
    def validate_position(cls, v):
        if len(v) != 2:
            raise ValueError('Position must be [x, y] coordinates')
        return v
    
    @validator('credentials', pre=True)
    def validate_credentials(cls, v):
        # Ensure credentials is always a dict, never None
        return v if v is not None else {}


class WorkflowConfig(BaseModel):
    """n8n workflow configuration"""
    name: str = Field(..., description="Workflow name")
    nodes: List[WorkflowNode] = Field(..., description="Workflow nodes")
    connections: Dict[str, Dict[str, List[List[WorkflowConnection]]]] = Field(
        default_factory=dict, 
        description="Node connections"
    )
    active: bool = Field(default=False, description="Whether workflow is active")
    settings: Dict[str, Any] = Field(default_factory=dict, description="Workflow settings")
    staticData: Dict[str, Any] = Field(default_factory=dict, description="Static workflow data")
    tags: List[str] = Field(default_factory=list, description="Workflow tags")
    
    def add_connection(self, from_node: str, to_node: str, 
                      from_type: str = "main", to_type: str = "main",
                      from_index: int = 0, to_index: int = 0):
        """Add connection between nodes"""
        if from_node not in self.connections:
            self.connections[from_node] = {}
        if from_type not in self.connections[from_node]:
            self.connections[from_node][from_type] = []
        
        # Ensure we have enough connection arrays
        while len(self.connections[from_node][from_type]) <= from_index:
            self.connections[from_node][from_type].append([])
        
        connection = WorkflowConnection(node=to_node, type=to_type, index=to_index)
        self.connections[from_node][from_type][from_index].append(connection)


class WorkflowTemplate(BaseModel):
    """Predefined workflow template"""
    id: str = Field(..., description="Template ID")
    name: str = Field(..., description="Template name")
    description: str = Field(..., description="Template description")
    category: str = Field(..., description="Template category")
    tags: List[str] = Field(default_factory=list, description="Template tags")
    workflow_config: WorkflowConfig = Field(..., description="Base workflow configuration")
    parameters: List[Dict[str, Any]] = Field(
        default_factory=list, 
        description="Configurable parameters"
    )
    
    def create_workflow(self, name: str, params: Dict[str, Any] = None) -> WorkflowConfig:
        """Create workflow from template with parameters"""
        config = self.workflow_config.copy(deep=True)
        config.name = name
        
        if params:
            # Apply parameters to nodes
            for node in config.nodes:
                for param_key, param_value in params.items():
                    if param_key in node.parameters:
                        node.parameters[param_key] = param_value
        
        return config


# Request/Response Models for API

class CreateWorkflowRequest(BaseModel):
    """Request to create n8n workflow"""
    name: str = Field(..., description="Workflow name")
    description: Optional[str] = Field(None, description="Workflow description")
    template_id: Optional[str] = Field(None, description="Template to use")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Workflow parameters")
    activate: bool = Field(default=False, description="Activate workflow after creation")


class N8nAutomationRequest(BaseModel):
    """Request for AI-driven n8n automation"""
    prompt: str = Field(..., description="Natural language automation request")
    model: str = Field(default="auto", description="AI model to use")
    session_id: Optional[str] = Field(None, description="Chat session ID")
    user_context: Optional[Dict[str, Any]] = Field(None, description="User context")


class WorkflowExecutionRequest(BaseModel):
    """Request to execute workflow"""
    workflow_id: str = Field(..., description="n8n workflow ID")
    input_data: Optional[Dict[str, Any]] = Field(None, description="Input data for execution")


class WorkflowResponse(BaseModel):
    """Response with workflow information"""
    id: str = Field(..., description="n8n workflow ID")
    name: str = Field(..., description="Workflow name")
    active: bool = Field(..., description="Whether workflow is active")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")
    url: Optional[str] = Field(None, description="n8n editor URL")


# Database Models

class WorkflowRecord(BaseModel):
    """Database record for created workflows"""
    id: Optional[int] = Field(None, description="Database ID")
    workflow_id: str = Field(..., description="n8n workflow ID")
    user_id: Optional[int] = Field(None, description="User who created workflow")
    name: str = Field(..., description="Workflow name")
    description: Optional[str] = Field(None, description="Workflow description")
    prompt: Optional[str] = Field(None, description="Original user prompt")
    template_id: Optional[str] = Field(None, description="Template used")
    config: Dict[str, Any] = Field(..., description="Full workflow configuration")
    status: str = Field(default="created", description="Workflow status")
    created_at: datetime = Field(default_factory=datetime.utcnow, description="Creation time")
    updated_at: datetime = Field(default_factory=datetime.utcnow, description="Last update time")


class AutomationHistory(BaseModel):
    """History of automation requests"""
    id: Optional[int] = Field(None, description="Database ID")
    user_id: Optional[int] = Field(None, description="User ID")
    prompt: str = Field(..., description="User prompt")
    response: str = Field(..., description="AI response")
    workflow_id: Optional[str] = Field(None, description="Created workflow ID")
    success: bool = Field(..., description="Whether automation succeeded")
    error_message: Optional[str] = Field(None, description="Error message if failed")
    execution_time: float = Field(..., description="Execution time in seconds")
    created_at: datetime = Field(default_factory=datetime.utcnow, description="Request time")


# Common workflow templates data structures

COMMON_TEMPLATES = {
    "weather_monitor": {
        "id": "weather_monitor",
        "name": "Weather Monitor",
        "description": "Fetch weather data on schedule and send notifications",
        "category": "monitoring",
        "tags": ["weather", "schedule", "notification"]
    },
    "web_scraper": {
        "id": "web_scraper", 
        "name": "Web Scraper",
        "description": "Scrape website data on schedule",
        "category": "data",
        "tags": ["scraping", "schedule", "data"]
    },
    "slack_notification": {
        "id": "slack_notification",
        "name": "Slack Notification",
        "description": "Send notifications to Slack channel",
        "category": "notification", 
        "tags": ["slack", "notification"]
    },
    "email_automation": {
        "id": "email_automation",
        "name": "Email Automation", 
        "description": "Automated email sending workflow",
        "category": "communication",
        "tags": ["email", "automation"]
    },
    "data_sync": {
        "id": "data_sync",
        "name": "Data Synchronization",
        "description": "Sync data between different systems",
        "category": "integration",
        "tags": ["sync", "data", "integration"]
    }
}