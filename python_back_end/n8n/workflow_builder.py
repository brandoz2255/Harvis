"""
n8n Workflow Builder

Creates n8n workflow configurations from templates and AI-generated requirements.
"""

import uuid
import logging
from typing import Dict, List, Optional, Any, Tuple
from .models import (
    WorkflowConfig, WorkflowNode, WorkflowConnection, WorkflowTemplate,
    NodeType, COMMON_TEMPLATES
)

logger = logging.getLogger(__name__)


class WorkflowBuilder:
    """
    Builds n8n workflow configurations from templates and requirements
    """
    
    def __init__(self):
        self.templates = self._load_templates()
        logger.info(f"Loaded {len(self.templates)} workflow templates")
    
    def _load_templates(self) -> Dict[str, WorkflowTemplate]:
        """Load predefined workflow templates"""
        templates = {}
        
        # Weather Monitor Template
        templates["weather_monitor"] = self._create_weather_template()
        
        # Web Scraper Template  
        templates["web_scraper"] = self._create_web_scraper_template()
        
        # Slack Notification Template
        templates["slack_notification"] = self._create_slack_template()
        
        # Email Automation Template
        templates["email_automation"] = self._create_email_template()
        
        # HTTP API Template
        templates["http_api"] = self._create_http_api_template()
        
        # Webhook Receiver Template
        templates["webhook_receiver"] = self._create_webhook_template()
        
        return templates
    
    def get_template(self, template_id: str) -> Optional[WorkflowTemplate]:
        """Get template by ID"""
        return self.templates.get(template_id)
    
    def list_templates(self) -> List[Dict[str, str]]:
        """List all available templates"""
        return [
            {
                "id": template.id,
                "name": template.name,
                "description": template.description,
                "category": template.category,
                "tags": template.tags
            }
            for template in self.templates.values()
        ]
    
    def build_from_template(self, template_id: str, name: str, 
                           parameters: Dict[str, Any] = None) -> WorkflowConfig:
        """
        Build workflow from template
        
        Args:
            template_id: Template to use
            name: Workflow name
            parameters: Template parameters
            
        Returns:
            WorkflowConfig ready for n8n
        """
        template = self.get_template(template_id)
        if not template:
            raise ValueError(f"Template {template_id} not found")
        
        config = template.create_workflow(name, parameters or {})
        logger.info(f"Built workflow '{name}' from template '{template_id}'")
        return config
    
    def build_simple_workflow(self, name: str, nodes: List[Dict[str, Any]], 
                             connections: List[Tuple[str, str]] = None) -> WorkflowConfig:
        """
        Build simple workflow from node definitions
        
        Args:
            name: Workflow name
            nodes: List of node configurations
            connections: List of (from_node, to_node) tuples
            
        Returns:
            WorkflowConfig ready for n8n
        """
        workflow_nodes = []
        node_positions = self._calculate_positions(len(nodes))
        
        logger.info(f"Building simple workflow with {len(nodes)} nodes")
        for i, node_def in enumerate(nodes):
            node_name = node_def.get("name", f"Node_{i+1}")
            node_type = node_def.get("type", NodeType.HTTP_REQUEST)
            logger.info(f"Creating WorkflowNode {i+1}: {node_name} (type: {node_type})")
            
            node = WorkflowNode(
                name=node_name,
                type=node_type,
                parameters=node_def.get("parameters", {}),
                position=node_positions[i],
                credentials=node_def.get("credentials") or {}
            )
            workflow_nodes.append(node)
            logger.info(f"Added WorkflowNode: {node.name} with type {node.type}")
        
        config = WorkflowConfig(name=name, nodes=workflow_nodes)
        
        # Add connections
        if connections:
            for from_node, to_node in connections:
                config.add_connection(from_node, to_node)
        else:
            # Auto-connect sequential nodes
            for i in range(len(workflow_nodes) - 1):
                config.add_connection(
                    workflow_nodes[i].name,
                    workflow_nodes[i + 1].name
                )
        
        logger.info(f"Built simple workflow '{name}' with {len(nodes)} nodes")
        return config
    
    def build_ai_workflow(self, name: str, description: str, 
                         requirements: Dict[str, Any]) -> WorkflowConfig:
        """
        Build workflow based on AI-analyzed requirements
        
        Args:
            name: Workflow name
            description: Workflow description
            requirements: Analyzed requirements from AI
            
        Returns:
            WorkflowConfig ready for n8n
        """
        # Determine workflow type from requirements
        workflow_type = self._analyze_workflow_type(requirements)
        
        if workflow_type in self.templates:
            # Use existing template
            return self.build_from_template(workflow_type, name, requirements)
        else:
            # Build custom workflow
            return self._build_custom_workflow(name, description, requirements)
    
    def _analyze_workflow_type(self, requirements: Dict[str, Any]) -> str:
        """Analyze requirements to determine best workflow type"""
        keywords = requirements.get("keywords", [])
        action_value = requirements.get("action", "")
        action = action_value.lower() if isinstance(action_value, str) else ""
        
        # Simple keyword matching
        if any(word in keywords for word in ["weather", "forecast"]):
            return "weather_monitor"
        elif any(word in keywords for word in ["scrape", "crawl", "extract"]):
            return "web_scraper"
        elif any(word in keywords for word in ["slack", "message", "notify"]):
            return "slack_notification"
        elif any(word in keywords for word in ["email", "mail", "send"]):
            return "email_automation"
        elif any(word in keywords for word in ["http", "api", "request"]):
            return "http_api"
        elif any(word in keywords for word in ["webhook", "receive", "trigger"]):
            return "webhook_receiver"
        else:
            return "custom"
    
    def _build_custom_workflow(self, name: str, description: str, 
                             requirements: Dict[str, Any]) -> WorkflowConfig:
        """Build custom workflow from requirements"""
        nodes = []
        
        # Check if nodes_required is specified in requirements (from AI analysis)
        nodes_required = requirements.get("nodes_required", [])
        parameters = requirements.get("parameters", {})
        
        if nodes_required:
            logger.info(f"Building workflow with AI-specified nodes: {nodes_required}")
            return self._build_workflow_from_ai_nodes(name, description, nodes_required, parameters, requirements)
        
        # Fallback to legacy action-based workflow building
        logger.info("No AI nodes specified, falling back to action-based workflow")
        
        # Always start with a trigger
        trigger_type = requirements.get("trigger", "manual")
        if trigger_type == "schedule":
            nodes.append({
                "name": "Schedule Trigger",
                "type": NodeType.SCHEDULE_TRIGGER,
                "parameters": {
                    "rule": {
                        "interval": requirements.get("schedule_interval", "daily")
                    }
                }
            })
        elif trigger_type == "webhook":
            nodes.append({
                "name": "Webhook",
                "type": NodeType.WEBHOOK,
                "parameters": {
                    "httpMethod": "POST",
                    "path": requirements.get("webhook_path", "/webhook")
                }
            })
        else:
            nodes.append({
                "name": "Manual Trigger",
                "type": NodeType.MANUAL_TRIGGER,
                "parameters": {}
            })
        
        # Add action nodes based on requirements
        actions = requirements.get("actions", [])
        for action in actions:
            if action.get("type") == "http_request":
                nodes.append({
                    "name": f"HTTP Request - {action.get('name', 'API Call')}",
                    "type": NodeType.HTTP_REQUEST,
                    "parameters": {
                        "url": action.get("url", ""),
                        "requestMethod": action.get("method", "GET"),
                        "headers": action.get("headers", {}),
                        "body": action.get("body", {})
                    }
                })
            elif action.get("type") == "email":
                nodes.append({
                    "name": f"Send Email - {action.get('name', 'Email')}",
                    "type": NodeType.EMAIL,
                    "parameters": {
                        "to": action.get("to", ""),
                        "subject": action.get("subject", ""),
                        "text": action.get("text", "")
                    }
                })
        
        return self.build_simple_workflow(name, nodes)
    
    def _build_workflow_from_ai_nodes(self, name: str, description: str, 
                                    nodes_required: List[str], parameters: Dict[str, Any],
                                    requirements: Dict[str, Any]) -> WorkflowConfig:
        """Build workflow from AI-identified node types"""
        logger.info(f"Building workflow from AI nodes: {nodes_required}")
        logger.info(f"Parameters: {parameters}")
        logger.info(f"Requirements: {requirements}")
        
        nodes = []
        
        # Determine trigger node from requirements
        trigger_type = requirements.get("trigger", "manual")
        has_trigger = any(self._is_trigger_node(node_type) for node_type in nodes_required)
        
        logger.info(f"Trigger type: {trigger_type}, has_trigger: {has_trigger}")
        
        if not has_trigger:
            # Add appropriate trigger if none specified
            if trigger_type == "schedule":
                nodes.append({
                    "name": "Schedule Trigger",
                    "type": NodeType.SCHEDULE_TRIGGER,
                    "parameters": {
                        "rule": {
                            "interval": requirements.get("schedule_interval", "daily")
                        }
                    }
                })
            elif trigger_type == "webhook":
                nodes.append({
                    "name": "Webhook",
                    "type": NodeType.WEBHOOK,
                    "parameters": {
                        "httpMethod": "POST",
                        "path": requirements.get("webhook_path", "/webhook")
                    }
                })
            else:
                nodes.append({
                    "name": "Manual Trigger",
                    "type": NodeType.MANUAL_TRIGGER,
                    "parameters": {}
                })
        
        # Process each AI-identified node
        logger.info(f"Processing {len(nodes_required)} AI-identified nodes")
        for i, node_type in enumerate(nodes_required):
            logger.info(f"Processing node {i+1}/{len(nodes_required)}: {node_type}")
            node_config = self._create_node_from_type(node_type, parameters, i, description)
            if node_config:
                nodes.append(node_config)
                logger.info(f"Added node: {node_config['name']} (type: {node_config['type']})")
            else:
                logger.warning(f"Failed to create node config for: {node_type}")
        
        logger.info(f"Total nodes to build into workflow: {len(nodes)}")
        for i, node in enumerate(nodes):
            logger.info(f"Node {i+1}: {node['name']} ({node['type']})")
        
        return self.build_simple_workflow(name, nodes)
    
    def _is_trigger_node(self, node_type: str) -> bool:
        """Check if node type is a trigger node"""
        trigger_keywords = ["trigger", "webhook", "schedule", "manual"]
        return any(keyword in node_type.lower() for keyword in trigger_keywords)
    
    def _create_node_from_type(self, node_type: str, parameters: Dict[str, Any], 
                              node_index: int, description: str = "") -> Optional[Dict[str, Any]]:
        """Create node configuration from n8n node type"""
        
        logger.info(f"Creating node for type: {node_type} with parameters: {list(parameters.keys())}")
        
        # Map specific node types to configurations
        node_mapping = {
            # LangChain nodes
            "@n8n/n8n-nodes-langchain.agent": {
                "name": "LangChain Agent",
                "type": "@n8n/n8n-nodes-langchain.agent",
                "parameters": {
                    "sessionId": parameters.get("session_id", "default"),
                    "model": parameters.get("model", "gpt-3.5-turbo"),
                    "prompt": parameters.get("prompt", "You are a helpful assistant")
                }
            },
            "@n8n/n8n-nodes-langchain.openAi": {
                "name": "OpenAI LLM",
                "type": "@n8n/n8n-nodes-langchain.openAi",
                "parameters": {
                    "model": parameters.get("model", "gpt-3.5-turbo"),
                    "temperature": parameters.get("temperature", 0.7),
                    "maxTokens": parameters.get("max_tokens", 1000)
                }
            },
            "@n8n/n8n-nodes-langchain.lmOllama": {
                "name": "Ollama LLM",
                "type": "@n8n/n8n-nodes-langchain.lmOllama",
                "parameters": {
                    "model": parameters.get("model", "mistral"),
                    "baseURL": parameters.get("base_url", "http://ollama:11434"),
                    "temperature": parameters.get("temperature", 0.7)
                }
            },
            
            # Base nodes
            "n8n-nodes-base.youTube": {
                "name": "YouTube",
                "type": "n8n-nodes-base.youTube",
                "parameters": {
                    "operation": parameters.get("youtube_operation", "search"),
                    "query": parameters.get("query", ""),
                    "maxResults": parameters.get("max_results", 10)
                }
            },
            "n8n-nodes-base.code": {
                "name": "Code",
                "type": "n8n-nodes-base.code",
                "parameters": {
                    "jsCode": parameters.get("code", "// Add your custom code here\\nreturn items;")
                }
            },
            "n8n-nodes-base.httpRequest": {
                "name": "HTTP Request",
                "type": "n8n-nodes-base.httpRequest",
                "parameters": {
                    "url": parameters.get("url", ""),
                    "requestMethod": parameters.get("method", "GET"),
                    "headers": parameters.get("headers", {}),
                    "body": parameters.get("body", {})
                }
            },
            "n8n-nodes-base.stickyNote": {
                "name": "Sticky Note",
                "type": "n8n-nodes-base.stickyNote",
                "parameters": {
                    "content": parameters.get("note", description if description else "Workflow note")
                }
            },
            "n8n-nodes-base.emailSend": {
                "name": "Send Email",
                "type": "n8n-nodes-base.emailSend",
                "parameters": {
                    "to": parameters.get("to", ""),
                    "subject": parameters.get("subject", ""),
                    "text": parameters.get("email_body", "")
                }
            },
            "n8n-nodes-base.slack": {
                "name": "Slack",
                "type": "n8n-nodes-base.slack",
                "parameters": {
                    "channel": parameters.get("channel", ""),
                    "text": parameters.get("message", "")
                }
            }
        }
        
        # Get base configuration
        base_config = node_mapping.get(node_type)
        if not base_config:
            # Create generic node for unknown types
            logger.warning(f"Unknown node type: {node_type}, creating generic node")
            base_config = {
                "name": f"Node {node_index + 1}",
                "type": node_type,
                "parameters": {}
            }
        else:
            logger.info(f"Found mapping for node type: {node_type} -> {base_config['name']}")
        
        # Create a copy and customize
        node_config = base_config.copy()
        
        # Add unique suffix if multiple nodes of same type
        if node_index > 0:
            node_config["name"] = f"{base_config['name']} {node_index + 1}"
        
        logger.info(f"Created node config: {node_config['name']} ({node_config['type']})")
        return node_config
    
    def _calculate_positions(self, node_count: int) -> List[List[int]]:
        """Calculate node positions for workflow layout"""
        positions = []
        x_start = 240
        y_start = 300
        x_spacing = 220
        
        for i in range(node_count):
            x = x_start + (i * x_spacing)
            y = y_start
            positions.append([x, y])
        
        return positions
    
    # Template creation methods
    
    def _create_weather_template(self) -> WorkflowTemplate:
        """Create weather monitoring template"""
        nodes = [
            WorkflowNode(
                name="Schedule Trigger",
                type=NodeType.SCHEDULE_TRIGGER,
                position=[240, 300],
                parameters={
                    "rule": {
                        "interval": "daily",
                        "hour": 8
                    }
                }
            ),
            WorkflowNode(
                name="Get Weather",
                type=NodeType.HTTP_REQUEST,
                position=[460, 300],
                parameters={
                    "url": "https://api.openweathermap.org/data/2.5/weather",
                    "requestMethod": "GET",
                    "qs": {
                        "q": "{{$parameter['city']}}",
                        "appid": "{{$parameter['api_key']}}",
                        "units": "metric"
                    }
                }
            ),
            WorkflowNode(
                name="Process Data",
                type=NodeType.CODE,
                position=[680, 300],
                parameters={
                    "jsCode": "const weather = items[0].json; return [{ json: { temperature: weather.main.temp, description: weather.weather[0].description, city: weather.name } }];"
                }
            )
        ]
        
        config = WorkflowConfig(name="Weather Monitor Template", nodes=nodes)
        config.add_connection("Schedule Trigger", "Get Weather")
        config.add_connection("Get Weather", "Process Data")
        
        return WorkflowTemplate(
            id="weather_monitor",
            name="Weather Monitor",
            description="Monitor weather conditions and send alerts",
            category="monitoring",
            tags=["weather", "monitoring", "api"],
            workflow_config=config,
            parameters=[
                {"name": "city", "type": "string", "description": "City name"},
                {"name": "api_key", "type": "string", "description": "OpenWeather API key"}
            ]
        )
    
    def _create_web_scraper_template(self) -> WorkflowTemplate:
        """Create web scraping template"""
        nodes = [
            WorkflowNode(
                name="Manual Trigger",
                type=NodeType.MANUAL_TRIGGER,
                position=[240, 300],
                parameters={}
            ),
            WorkflowNode(
                name="HTTP Request",
                type=NodeType.HTTP_REQUEST,
                position=[460, 300],
                parameters={
                    "url": "{{$parameter['url']}}",
                    "requestMethod": "GET"
                }
            ),
            WorkflowNode(
                name="Extract Data",
                type=NodeType.CODE,
                position=[680, 300],
                parameters={
                    "jsCode": "// Add your data extraction logic here\nreturn items;"
                }
            )
        ]
        
        config = WorkflowConfig(name="Web Scraper Template", nodes=nodes)
        config.add_connection("Manual Trigger", "HTTP Request")
        config.add_connection("HTTP Request", "Extract Data")
        
        return WorkflowTemplate(
            id="web_scraper",
            name="Web Scraper",
            description="Scrape data from websites",
            category="data",
            tags=["scraping", "data", "extraction"],
            workflow_config=config,
            parameters=[
                {"name": "url", "type": "string", "description": "Target URL"},
                {"name": "selector", "type": "string", "description": "CSS selector"}
            ]
        )
    
    def _create_slack_template(self) -> WorkflowTemplate:
        """Create Slack notification template"""
        nodes = [
            WorkflowNode(
                name="Manual Trigger",
                type=NodeType.MANUAL_TRIGGER,
                position=[240, 300],
                parameters={}
            ),
            WorkflowNode(
                name="Slack",
                type=NodeType.SLACK,
                position=[460, 300],
                parameters={
                    "channel": "{{$parameter['channel']}}",
                    "text": "{{$parameter['message']}}"
                }
            )
        ]
        
        config = WorkflowConfig(name="Slack Notification Template", nodes=nodes)
        config.add_connection("Manual Trigger", "Slack")
        
        return WorkflowTemplate(
            id="slack_notification",
            name="Slack Notification",
            description="Send notifications to Slack",
            category="communication",
            tags=["slack", "notification", "messaging"],
            workflow_config=config,
            parameters=[
                {"name": "channel", "type": "string", "description": "Slack channel"},
                {"name": "message", "type": "string", "description": "Message text"}
            ]
        )
    
    def _create_email_template(self) -> WorkflowTemplate:
        """Create email automation template"""
        nodes = [
            WorkflowNode(
                name="Manual Trigger",
                type=NodeType.MANUAL_TRIGGER,
                position=[240, 300],
                parameters={}
            ),
            WorkflowNode(
                name="Send Email",
                type=NodeType.EMAIL,
                position=[460, 300],
                parameters={
                    "to": "{{$parameter['to']}}",
                    "subject": "{{$parameter['subject']}}",
                    "text": "{{$parameter['body']}}"
                }
            )
        ]
        
        config = WorkflowConfig(name="Email Automation Template", nodes=nodes)
        config.add_connection("Manual Trigger", "Send Email")
        
        return WorkflowTemplate(
            id="email_automation",
            name="Email Automation",
            description="Automated email sending",
            category="communication",
            tags=["email", "automation", "notification"],
            workflow_config=config,
            parameters=[
                {"name": "to", "type": "string", "description": "Recipient email"},
                {"name": "subject", "type": "string", "description": "Email subject"},
                {"name": "body", "type": "string", "description": "Email body"}
            ]
        )
    
    def _create_http_api_template(self) -> WorkflowTemplate:
        """Create HTTP API call template"""
        nodes = [
            WorkflowNode(
                name="Manual Trigger",
                type=NodeType.MANUAL_TRIGGER,
                position=[240, 300],
                parameters={}
            ),
            WorkflowNode(
                name="HTTP Request",
                type=NodeType.HTTP_REQUEST,
                position=[460, 300],
                parameters={
                    "url": "{{$parameter['url']}}",
                    "requestMethod": "{{$parameter['method']}}",
                    "headers": {},
                    "body": {}
                }
            )
        ]
        
        config = WorkflowConfig(name="HTTP API Template", nodes=nodes)
        config.add_connection("Manual Trigger", "HTTP Request")
        
        return WorkflowTemplate(
            id="http_api",
            name="HTTP API Call",
            description="Make HTTP API requests",
            category="integration",
            tags=["http", "api", "integration"],
            workflow_config=config,
            parameters=[
                {"name": "url", "type": "string", "description": "API endpoint URL"},
                {"name": "method", "type": "string", "description": "HTTP method"}
            ]
        )
    
    def _create_webhook_template(self) -> WorkflowTemplate:
        """Create webhook receiver template"""
        nodes = [
            WorkflowNode(
                name="Webhook",
                type=NodeType.WEBHOOK,
                position=[240, 300],
                parameters={
                    "httpMethod": "POST",
                    "path": "{{$parameter['path']}}"
                }
            ),
            WorkflowNode(
                name="Process Webhook",
                type=NodeType.CODE,
                position=[460, 300],
                parameters={
                    "jsCode": "// Process webhook data\nreturn items;"
                }
            )
        ]
        
        config = WorkflowConfig(name="Webhook Receiver Template", nodes=nodes)
        config.add_connection("Webhook", "Process Webhook")
        
        return WorkflowTemplate(
            id="webhook_receiver",
            name="Webhook Receiver",
            description="Receive and process webhooks",
            category="integration",
            tags=["webhook", "trigger", "integration"],
            workflow_config=config,
            parameters=[
                {"name": "path", "type": "string", "description": "Webhook path"}
            ]
        )