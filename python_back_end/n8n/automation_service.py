"""
n8n Automation Service

AI-powered n8n workflow creation service that interprets natural language requests
and automatically generates appropriate n8n workflows.
"""

import time
import logging
import requests
import json
from typing import Dict, List, Optional, Any, Tuple
from .client import N8nClient, N8nClientError
from .workflow_builder import WorkflowBuilder
from .storage import N8nStorage
from .models import (
    WorkflowRecord, AutomationHistory, CreateWorkflowRequest, 
    N8nAutomationRequest, WorkflowResponse
)

logger = logging.getLogger(__name__)


class N8nAutomationService:
    """
    Main service for AI-powered n8n workflow automation
    
    Combines AI language processing with n8n workflow creation to enable
    natural language workflow automation.
    """
    
    def __init__(self, n8n_client: N8nClient, workflow_builder: WorkflowBuilder, 
                 storage: N8nStorage, ollama_url: str = "http://ollama:11434"):
        """
        Initialize automation service
        
        Args:
            n8n_client: Configured n8n API client
            workflow_builder: Workflow builder instance
            storage: Database storage instance
            ollama_url: Ollama server URL for AI processing
        """
        self.n8n_client = n8n_client
        self.workflow_builder = workflow_builder
        self.storage = storage
        self.ollama_url = ollama_url
        
        logger.info("Initialized n8n automation service")
    
    async def process_automation_request(self, request: N8nAutomationRequest, 
                                       user_id: Optional[int] = None) -> Dict[str, Any]:
        """
        Process natural language automation request
        
        Args:
            request: Automation request with prompt and parameters
            user_id: Optional user ID for tracking
            
        Returns:
            Response with workflow information or error details
        """
        start_time = time.time()
        
        try:
            logger.info(f"Processing automation request: {request.prompt[:100]}...")
            
            # Step 1: Analyze user prompt with AI
            analysis = await self._analyze_user_prompt(request.prompt, request.model)
            
            if not analysis.get("feasible", False):
                return {
                    "success": False,
                    "error": "Could not understand automation request",
                    "suggestions": analysis.get("suggestions", [])
                }
            
            # Step 2: Create workflow based on analysis
            workflow_config = await self._create_workflow_from_analysis(
                analysis, request.prompt
            )
            
            # Step 3: Create workflow in n8n
            n8n_workflow = self.n8n_client.create_workflow(workflow_config.dict())
            workflow_id = n8n_workflow.get("id")
            
            # Step 4: Activate workflow if requested
            if analysis.get("auto_activate", False):
                try:
                    self.n8n_client.activate_workflow(workflow_id)
                    logger.info(f"Auto-activated workflow {workflow_id}")
                except N8nClientError as e:
                    logger.warning(f"Failed to auto-activate workflow: {e}")
            
            # Step 5: Save to database
            if user_id:
                workflow_record = WorkflowRecord(
                    workflow_id=workflow_id,
                    user_id=user_id,
                    name=workflow_config.name,
                    description=analysis.get("description", ""),
                    prompt=request.prompt,
                    template_id=analysis.get("template_id"),
                    config=workflow_config.dict(),
                    status="created"
                )
                await self.storage.save_workflow(workflow_record)
            
            # Step 6: Save automation history
            execution_time = time.time() - start_time
            if user_id:
                history = AutomationHistory(
                    user_id=user_id,
                    prompt=request.prompt,
                    response=f"Created workflow: {workflow_config.name}",
                    workflow_id=workflow_id,
                    success=True,
                    execution_time=execution_time
                )
                await self.storage.save_automation_history(history)
            
            logger.info(f"Successfully created workflow {workflow_id} in {execution_time:.2f}s")
            
            return {
                "success": True,
                "workflow": {
                    "id": workflow_id,
                    "name": workflow_config.name,
                    "description": analysis.get("description", ""),
                    "active": analysis.get("auto_activate", False),
                    "url": f"{self.n8n_client.base_url}/workflow/{workflow_id}",
                    "template_used": analysis.get("template_id")
                },
                "analysis": analysis,
                "execution_time": execution_time
            }
            
        except Exception as e:
            execution_time = time.time() - start_time
            logger.error(f"Automation request failed: {e}")
            
            # Save failed attempt to history
            if user_id:
                try:
                    history = AutomationHistory(
                        user_id=user_id,
                        prompt=request.prompt,
                        response=f"Failed: {str(e)}",
                        success=False,
                        error_message=str(e),
                        execution_time=execution_time
                    )
                    await self.storage.save_automation_history(history)
                except Exception as storage_error:
                    logger.error(f"Failed to save error history: {storage_error}")
            
            return {
                "success": False,
                "error": str(e),
                "execution_time": execution_time
            }
    
    async def _analyze_user_prompt(self, prompt: str, model: str = "mistral") -> Dict[str, Any]:
        """
        Analyze user prompt with AI to extract workflow requirements
        
        Args:
            prompt: User's natural language request
            model: AI model to use for analysis
            
        Returns:
            Analysis results with workflow requirements
        """
        system_prompt = """You are an n8n workflow automation expert. You are creative and helpful, finding ways to automate almost any request through n8n workflows. Analyze user requests and determine:

1. Whether the request is feasible for n8n automation (be flexible and creative)
2. What type of workflow is needed
3. What nodes and connections are required
4. What parameters need to be configured
5. Whether to auto-activate the workflow

IMPORTANT: Be creative and flexible. Most requests can be automated in some way. Even complex requests like "AI customer service team" can be implemented as workflows with HTTP requests, webhooks, and integrations.

Respond in JSON format with these fields:
- feasible (boolean): Whether request can be automated with n8n (default to true unless impossible)
- workflow_type (string): Type of workflow (schedule, webhook, manual, api)
- template_id (string): Best matching template ID if available
- description (string): Clear description of what workflow will do
- auto_activate (boolean): Whether to activate immediately
- nodes_required (array): List of required n8n node types
- parameters (object): Key configuration parameters
- schedule (object): If scheduled, timing details
- suggestions (array): Alternative suggestions if not feasible

Available templates: weather_monitor, web_scraper, slack_notification, email_automation, http_api, webhook_receiver

Common node types: manual trigger, schedule trigger, webhook, http request, email send, slack, discord, code function, if condition, switch, merge, split, set, move binary data

Examples:
- "AI customer service team" → webhook workflow with HTTP requests to AI APIs
- "Monitor website" → schedule workflow with HTTP requests and notifications
- "Send daily reports" → schedule workflow with data processing and email
- "Process form submissions" → webhook workflow with data validation and storage"""
        
        user_prompt = f"""Analyze this automation request: "{prompt}"
        
Determine what kind of n8n workflow this needs and provide detailed analysis."""
        
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "stream": False,
            "format": "json"
        }
        
        try:
            logger.info(f"Analyzing prompt with {model}")
            response = requests.post(
                f"{self.ollama_url}/api/chat",
                json=payload,
                timeout=60
            )
            response.raise_for_status()
            
            ai_response = response.json().get("message", {}).get("content", "")
            analysis = json.loads(ai_response)
            
            logger.info(f"AI analysis complete: {analysis.get('workflow_type', 'unknown')} workflow")
            return analysis
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse AI response as JSON: {e}")
            return {
                "feasible": False,
                "error": "Could not parse AI analysis",
                "suggestions": ["Please rephrase your request more clearly"]
            }
        except Exception as e:
            logger.error(f"AI analysis failed: {e}")
            return {
                "feasible": False,
                "error": f"AI analysis error: {str(e)}",
                "suggestions": ["Please try again or contact support"]
            }
    
    async def _create_workflow_from_analysis(self, analysis: Dict[str, Any], 
                                           original_prompt: str) -> Any:
        """
        Create workflow configuration from AI analysis
        
        Args:
            analysis: AI analysis results
            original_prompt: Original user prompt
            
        Returns:
            WorkflowConfig ready for n8n
        """
        workflow_name = self._generate_workflow_name(analysis, original_prompt)
        
        # Try to use template if available
        template_id = analysis.get("template_id")
        if template_id and template_id in self.workflow_builder.templates:
            logger.info(f"Using template {template_id}")
            parameters = analysis.get("parameters", {})
            return self.workflow_builder.build_from_template(template_id, workflow_name, parameters)
        
        # Build custom workflow from analysis
        logger.info("Building custom workflow from analysis")
        requirements = {
            "trigger": analysis.get("workflow_type", "manual"),
            "actions": self._extract_actions_from_analysis(analysis),
            "schedule_interval": analysis.get("schedule", {}).get("interval", "daily"),
            "webhook_path": analysis.get("parameters", {}).get("webhook_path", "/webhook"),
            "keywords": self._extract_keywords_from_prompt(original_prompt)
        }
        
        return self.workflow_builder.build_ai_workflow(
            workflow_name,
            analysis.get("description", "AI-generated workflow"),
            requirements
        )
    
    def _generate_workflow_name(self, analysis: Dict[str, Any], prompt: str) -> str:
        """Generate appropriate workflow name"""
        if analysis.get("template_id"):
            template_name = analysis.get("template_id", "").replace("_", " ").title()
            return f"{template_name} - {prompt[:30]}..."
        else:
            # Extract action from prompt
            prompt_words = prompt.lower().split()
            action_words = ["send", "fetch", "monitor", "check", "sync", "update", "create"]
            action = next((word for word in prompt_words if word in action_words), "automation")
            return f"Custom {action.title()} Workflow"
    
    def _extract_actions_from_analysis(self, analysis: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Extract action nodes from analysis"""
        actions = []
        nodes_required = analysis.get("nodes_required", [])
        parameters = analysis.get("parameters", {})
        
        for node_type in nodes_required:
            if "http" in node_type.lower():
                actions.append({
                    "type": "http_request",
                    "name": "API Call",
                    "url": parameters.get("url", ""),
                    "method": parameters.get("method", "GET"),
                    "headers": parameters.get("headers", {}),
                    "body": parameters.get("body", {})
                })
            elif "email" in node_type.lower():
                actions.append({
                    "type": "email",
                    "name": "Send Email",
                    "to": parameters.get("to", ""),
                    "subject": parameters.get("subject", ""),
                    "text": parameters.get("body", "")
                })
            elif "slack" in node_type.lower():
                actions.append({
                    "type": "slack",
                    "name": "Slack Message",
                    "channel": parameters.get("channel", ""),
                    "text": parameters.get("message", "")
                })
        
        return actions
    
    def _extract_keywords_from_prompt(self, prompt: str) -> List[str]:
        """Extract keywords from user prompt"""
        # Simple keyword extraction
        common_words = {"the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "of", "with", "by"}
        words = [word.lower().strip(".,!?") for word in prompt.split()]
        keywords = [word for word in words if len(word) > 3 and word not in common_words]
        return keywords[:10]  # Limit to top 10 keywords
    
    # Convenience methods for common operations
    
    async def create_simple_workflow(self, request: CreateWorkflowRequest, 
                                   user_id: Optional[int] = None) -> Dict[str, Any]:
        """
        Create workflow from simple template-based request
        
        Args:
            request: Simple workflow creation request
            user_id: Optional user ID
            
        Returns:
            Created workflow information
        """
        try:
            if request.template_id:
                # Use specified template
                workflow_config = self.workflow_builder.build_from_template(
                    request.template_id, request.name, request.parameters
                )
            else:
                # Build minimal workflow
                nodes = [{"name": "Manual Trigger", "type": "n8n-nodes-base.manualTrigger", "parameters": {}}]
                workflow_config = self.workflow_builder.build_simple_workflow(request.name, nodes)
            
            # Create in n8n
            n8n_workflow = self.n8n_client.create_workflow(workflow_config.dict())
            workflow_id = n8n_workflow.get("id")
            
            # Activate if requested
            if request.activate:
                self.n8n_client.activate_workflow(workflow_id)
            
            # Save to database
            if user_id:
                workflow_record = WorkflowRecord(
                    workflow_id=workflow_id,
                    user_id=user_id,
                    name=request.name,
                    description=request.description,
                    template_id=request.template_id,
                    config=workflow_config.dict(),
                    status="created"
                )
                await self.storage.save_workflow(workflow_record)
            
            return {
                "success": True,
                "workflow": {
                    "id": workflow_id,
                    "name": workflow_config.name,
                    "active": request.activate,
                    "url": f"{self.n8n_client.base_url}/workflow/{workflow_id}"
                }
            }
            
        except Exception as e:
            logger.error(f"Simple workflow creation failed: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def list_user_workflows(self, user_id: int) -> List[Dict[str, Any]]:
        """List workflows for user"""
        try:
            workflow_records = await self.storage.list_user_workflows(user_id)
            workflows = []
            
            for record in workflow_records:
                # Get current status from n8n
                try:
                    n8n_workflow = self.n8n_client.get_workflow(record.workflow_id)
                    active = n8n_workflow.get("active", False)
                except N8nClientError:
                    active = False
                
                workflows.append({
                    "id": record.workflow_id,
                    "name": record.name,
                    "description": record.description,
                    "template_id": record.template_id,
                    "status": record.status,
                    "active": active,
                    "created_at": record.created_at.isoformat(),
                    "url": f"{self.n8n_client.base_url}/workflow/{record.workflow_id}"
                })
            
            return workflows
            
        except Exception as e:
            logger.error(f"Failed to list user workflows: {e}")
            raise
    
    async def get_automation_history(self, user_id: int) -> List[Dict[str, Any]]:
        """Get automation history for user"""
        try:
            history_records = await self.storage.get_automation_history(user_id)
            history = []
            
            for record in history_records:
                history.append({
                    "id": record.id,
                    "prompt": record.prompt,
                    "response": record.response,
                    "workflow_id": record.workflow_id,
                    "success": record.success,
                    "error_message": record.error_message,
                    "execution_time": record.execution_time,
                    "created_at": record.created_at.isoformat()
                })
            
            return history
            
        except Exception as e:
            logger.error(f"Failed to get automation history: {e}")
            raise
    
    async def test_connection(self) -> Dict[str, Any]:
        """Test n8n connection and service health"""
        try:
            # Test n8n connection
            n8n_connected = self.n8n_client.test_connection()
            
            # Test AI service
            ai_test = await self._test_ai_service()
            
            # Test database
            db_connected = await self._test_database()
            
            return {
                "n8n_connected": n8n_connected,
                "ai_service": ai_test,
                "database_connected": db_connected,
                "overall_health": n8n_connected and ai_test and db_connected
            }
            
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return {
                "n8n_connected": False,
                "ai_service": False,
                "database_connected": False,
                "overall_health": False,
                "error": str(e)
            }
    
    async def _test_ai_service(self) -> bool:
        """Test AI service connectivity"""
        try:
            response = requests.get(f"{self.ollama_url}/api/tags", timeout=10)
            return response.status_code == 200
        except Exception:
            return False
    
    async def _test_database(self) -> bool:
        """Test database connectivity"""
        try:
            await self.storage.ensure_tables()
            return True
        except Exception:
            return False