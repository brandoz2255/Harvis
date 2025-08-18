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

# ─── Ollama Configuration with Cloud/Local Fallback ──────────────────────────
import os
CLOUD_OLLAMA_URL = "https://coyotegpt.ngrok.app/ollama"
LOCAL_OLLAMA_URL = "http://ollama:11434"
API_KEY = os.getenv("OLLAMA_API_KEY", "key")

def make_ollama_request(endpoint, payload, timeout=90):
    """Make a POST request to Ollama with automatic fallback from cloud to local.
    Returns the response object from the successful request."""
    headers = {"Authorization": f"Bearer {API_KEY}"} if API_KEY != "key" else {}
    
    # Try cloud first
    try:
        logger.info("🌐 Trying cloud Ollama: %s", CLOUD_OLLAMA_URL)
        response = requests.post(f"{CLOUD_OLLAMA_URL}{endpoint}", json=payload, headers=headers, timeout=timeout)
        if response.status_code == 200:
            logger.info("✅ Cloud Ollama request successful")
            return response
        else:
            logger.warning("⚠️ Cloud Ollama returned status %s", response.status_code)
    except Exception as e:
        logger.warning("⚠️ Cloud Ollama request failed: %s", e)
    
    # Fallback to local
    try:
        logger.info("🏠 Falling back to local Ollama: %s", LOCAL_OLLAMA_URL)
        response = requests.post(f"{LOCAL_OLLAMA_URL}{endpoint}", json=payload, timeout=timeout)
        if response.status_code == 200:
            logger.info("✅ Local Ollama request successful")
            return response
        else:
            logger.error("❌ Local Ollama returned status %s", response.status_code)
            response.raise_for_status()
    except Exception as e:
        logger.error("❌ Local Ollama request failed: %s", e)
        raise
    
    return response


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
            logger.debug(f"Workflow config type: {type(workflow_config)}")
            logger.debug(f"Workflow config dict method exists: {hasattr(workflow_config, 'dict')}")
            
            if hasattr(workflow_config, 'dict') and callable(getattr(workflow_config, 'dict')):
                workflow_data = workflow_config.dict()
            else:
                # Fallback for DirectWorkflow objects
                workflow_data = workflow_config.workflow_data if hasattr(workflow_config, 'workflow_data') else workflow_config
            
            logger.debug(f"Workflow data type: {type(workflow_data)}")
            n8n_workflow = self.n8n_client.create_workflow(workflow_data)
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
            
            # Get the full n8n workflow JSON from the created workflow
            full_workflow = n8n_workflow.copy()
            
            # Add our metadata to the full workflow
            full_workflow.update({
                "description": analysis.get("description", ""),
                "template_used": analysis.get("template_id"),
                "url": f"{self.n8n_client.base_url}/workflow/{workflow_id}",
                "execution_time": execution_time,
                "ai_generated": True
            })
            
            return {
                "success": True,
                "workflow": full_workflow,
                "metadata": {
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
            import traceback
            execution_time = time.time() - start_time
            logger.error(f"Automation request failed: {e}")
            logger.error(f"Full traceback: {traceback.format_exc()}")
            
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
    
    async def _analyze_user_prompt(self, prompt: str, model: str = "auto") -> Dict[str, Any]:
        """
        Analyze user prompt with AI to extract workflow requirements
        
        Args:
            prompt: User's natural language request
            model: AI model to use for analysis
            
        Returns:
            Analysis results with workflow requirements
        """
        # Handle auto model selection - default to mistral for n8n workflows
        if model == "auto":
            model = "mistral"  # Mistral is good for structured JSON generation
            logger.info(f"Auto-selected model: {model} for n8n workflow generation")
        
        system_prompt = """You are an n8n workflow automation expert. Generate COMPLETE n8n workflow JSON that can be directly imported into n8n.

CRITICAL: Your response must be a valid JSON object that matches n8n's exact import format.

REQUIRED JSON Structure (copy this exactly):
{
  "feasible": true,
  "workflow_type": "direct_json",
  "complete_workflow": {
    "name": "Descriptive Workflow Name",
    "nodes": [
      {
        "id": "generate-actual-uuid-like-a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        "name": "Descriptive Node Name (NOT Node 1, Node 2)",
        "type": "exact-n8n-node-type",
        "typeVersion": 1,
        "position": [240, 300],
        "parameters": {},
        "credentials": {}
      }
    ],
    "connections": {
      "Node Name": {
        "main": [
          [
            {
              "node": "Target Node Name",
              "type": "main", 
              "index": 0
            }
          ]
        ]
      }
    },
    "active": false,
    "settings": {"executionOrder": "v1"},
    "staticData": {},
    "tags": []
  },
  "description": "What this workflow does"
}

EXACT n8n Node Types to Use:
- "n8n-nodes-base.manualTrigger" (NOT "manual trigger")
- "n8n-nodes-base.scheduleTrigger" (NOT "schedule trigger") 
- "n8n-nodes-base.webhook"
- "n8n-nodes-base.httpRequest"
- "n8n-nodes-base.emailSend"
- "n8n-nodes-base.slack"
- "n8n-nodes-base.code"
- "n8n-nodes-base.googleSheets" (NOT "google sheets")
- "n8n-nodes-base.youTube"
- "n8n-nodes-base.twitter" (for Twitter posting)
- "n8n-nodes-base.facebook" (for Facebook posting)  
- "n8n-nodes-base.linkedIn" (for LinkedIn posting)
- "n8n-nodes-base.if" (for conditions)
- "n8n-nodes-base.set" (for data transformation)
- "@n8n/n8n-nodes-langchain.lmOllama" (for AI/LLM operations only)

MANDATORY Rules:
1. Each node MUST have unique UUID in "id" field (format: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx)
2. Use descriptive node names like "Schedule Daily Trigger", "Fetch Weather Data", "Send Notification"
3. Use EXACT n8n node types from list above
4. Position nodes horizontally: [240, 300], [460, 300], [680, 300], etc.
5. Generate REAL UUIDs - not placeholder text like "generate-random-uuid"
6. Connect nodes properly in "connections" object

UUID Generation Examples:
- "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
- "f47ac10b-58cc-4372-a567-0e02b2c3d479"
- "6ba7b810-9dad-11d1-80b4-00c04fd430c8"

CRITICAL Node Type Usage:
- Social Media: Use "n8n-nodes-base.twitter", "n8n-nodes-base.facebook", "n8n-nodes-base.linkedIn"
- Data Sources: Use "n8n-nodes-base.googleSheets", "n8n-nodes-base.airtable"
- Communication: Use "n8n-nodes-base.emailSend", "n8n-nodes-base.slack"
- AI/LLM: ONLY use "@n8n/n8n-nodes-langchain.lmOllama" for AI text generation
- Logic: Use "n8n-nodes-base.if", "n8n-nodes-base.switch" for conditions
- Data: Use "n8n-nodes-base.set", "n8n-nodes-base.code" for data transformation

NEVER use generic names like "Node 1", "Node 2 2", "Node 3 3".
NEVER use "@n8n/n8n-nodes-langchain.lmOllama" for social media posting - use proper social media nodes."""
        
        user_prompt = f"""Create a complete n8n workflow for: "{prompt}"

Generate the full JSON response following the exact structure above. The workflow should be directly importable into n8n."""
        
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
            logger.debug(f"Prompt length: {len(user_prompt)} characters")
            
            response = make_ollama_request("/api/chat", payload, timeout=120)
            response.raise_for_status()
            
            response_json = response.json()
            logger.debug(f"Full Ollama response: {response_json}")
            
            ai_response = response_json.get("message", {}).get("content", "")
            
            # Handle empty or whitespace-only responses
            if not ai_response or not ai_response.strip():
                logger.warning("AI returned empty response")
                ai_response = response_json.get("response", "")  # Try alternative field
                
            if not ai_response or not ai_response.strip():
                logger.error("AI response is empty or whitespace only")
                raise Exception("AI model returned empty response")
            
            logger.debug(f"AI response (first 500 chars): {ai_response[:500]}...")
            
            # Try to clean up the response if it has extra text
            cleaned_response = ai_response.strip()
            
            # If response doesn't start with {, try to extract JSON
            if not cleaned_response.startswith('{'):
                # Look for JSON in the response
                import re
                json_match = re.search(r'\{.*\}', cleaned_response, re.DOTALL)
                if json_match:
                    cleaned_response = json_match.group(0)
                    logger.info("Extracted JSON from AI response")
                else:
                    logger.error(f"No JSON found in AI response: {cleaned_response[:200]}...")
                    raise json.JSONDecodeError("No valid JSON found in response", cleaned_response, 0)
            
            analysis = json.loads(cleaned_response)
            
            logger.info(f"AI analysis complete: {analysis.get('workflow_type', 'unknown')} workflow")
            return analysis
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse AI response as JSON: {e}")
            logger.error(f"Raw AI response: {ai_response}")
            
            # If this was an enhanced prompt, try fallback with simple prompt
            if "Similar Workflow Examples for Reference:" in prompt:
                logger.info("Enhanced prompt failed, trying fallback analysis")
                # Extract just the original user request
                original_request = prompt.split("USER REQUEST TO IMPLEMENT:")[-1].split("Copy the best matching example")[0].strip()
                if not original_request:
                    original_request = prompt.split("REQUEST:")[-1].split("Copy the best matching example")[0].strip()
                
                # Retry with simple analysis
                return await self._analyze_user_prompt(original_request, model)
            
            
            return {
                "feasible": False,
                "error": "Could not parse AI analysis",
                "suggestions": ["Please rephrase your request more clearly"]
            }
        except Exception as e:
            logger.error(f"AI analysis failed: {e}")
            
            # If this was an enhanced prompt, try fallback
            if "Similar Workflow Examples for Reference:" in prompt:
                logger.info("Enhanced prompt caused error, trying fallback analysis")
                original_request = prompt.split("REQUEST:")[-1].split("Copy the best matching example")[0].strip()
                if original_request:
                    return await self._analyze_user_prompt(original_request, model)
            
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
        # Add debug logging for analysis
        logger.info(f"Creating workflow from analysis: {analysis}")
        
        workflow_name = self._generate_workflow_name(analysis, original_prompt)
        
        # Check if this is a direct JSON workflow from AI
        workflow_type = analysis.get("workflow_type", "manual")
        if workflow_type == "direct_json":
            logger.info("🎯 Using direct JSON workflow from AI")
            complete_workflow = analysis.get("complete_workflow")
            if complete_workflow:
                logger.info("✅ AI provided complete workflow JSON - bypassing workflow builder entirely")
                
                # Ensure the workflow has proper name and description
                if "name" not in complete_workflow or not complete_workflow["name"]:
                    complete_workflow["name"] = workflow_name
                if "description" not in complete_workflow:
                    complete_workflow["description"] = analysis.get("description", "AI-generated workflow")
                
                # Return the complete workflow directly without using WorkflowConfig models
                class DirectWorkflow:
                    def __init__(self, workflow_data):
                        self.workflow_data = workflow_data
                        self.name = workflow_data.get("name")
                        self.description = workflow_data.get("description")
                    
                    def dict(self):
                        return self.workflow_data
                
                return DirectWorkflow(complete_workflow)
            else:
                logger.warning("⚠️ Direct JSON type but no complete_workflow provided, falling back")
                return self._build_custom_workflow_from_vector_analysis(analysis, workflow_name)
        elif workflow_type == "custom_with_structure":
            logger.info("Building workflow from AI-provided complete structure")
            # Check for both field names (complete_workflow and full_workflow)
            full_workflow = analysis.get("complete_workflow") or analysis.get("full_workflow")
            if full_workflow:
                logger.info("✅ Using AI-generated complete workflow structure")
                # Add necessary metadata
                full_workflow["name"] = workflow_name
                full_workflow["description"] = analysis.get("description", "AI-generated from vector examples")
                
                # Return the complete workflow directly without using WorkflowConfig models
                class DirectWorkflow:
                    def __init__(self, workflow_data):
                        self.workflow_data = workflow_data
                        self.name = workflow_data.get("name")
                        self.description = workflow_data.get("description")
                    
                    def dict(self):
                        return self.workflow_data
                
                return DirectWorkflow(full_workflow)
            else:
                logger.warning("custom_with_structure specified but no complete_workflow provided, falling back to node-based building")
                return self._build_custom_workflow_from_vector_analysis(analysis, workflow_name)
        elif workflow_type == "custom":
            logger.info("Building workflow directly from vector store examples")
            # Check if AI provided a complete workflow structure
            full_workflow = analysis.get("full_workflow")
            if full_workflow:
                logger.info("Using AI-generated complete workflow structure")
                # Add necessary metadata
                full_workflow["name"] = workflow_name
                full_workflow["description"] = analysis.get("description", "AI-generated from vector examples")
                from .models import WorkflowConfig
                return WorkflowConfig(**full_workflow)
            else:
                logger.info("Building custom workflow from vector analysis")
                # Use enhanced custom workflow building
                return self._build_custom_workflow_from_vector_analysis(analysis, workflow_name)
        
        # Try to use template if available
        template_id = analysis.get("template_id")
        if template_id and template_id in self.workflow_builder.templates:
            logger.info(f"Using template {template_id}")
            parameters = analysis.get("parameters") or {}
            return self.workflow_builder.build_from_template(template_id, workflow_name, parameters)
        
        # Build custom workflow from analysis
        logger.info("Building custom workflow from analysis")
        
        # Safely extract nested values with proper null checking
        schedule = analysis.get("schedule") or {}
        parameters = analysis.get("parameters") or {}
        nodes_required = analysis.get("nodes_required", [])
        
        requirements = {
            "trigger": analysis.get("workflow_type", "manual"),
            "actions": self._extract_actions_from_analysis(analysis),
            "schedule_interval": schedule.get("interval", "daily"),
            "webhook_path": parameters.get("webhook_path", "/webhook"),
            "keywords": self._extract_keywords_from_prompt(original_prompt),
            "nodes_required": nodes_required,  # Pass AI-identified nodes
            "parameters": parameters  # Pass all AI analysis parameters
        }
        
        return self.workflow_builder.build_ai_workflow(
            workflow_name,
            analysis.get("description", "AI-generated workflow"),
            requirements
        )
    
    def _build_custom_workflow_from_vector_analysis(self, analysis: Dict[str, Any], workflow_name: str) -> Any:
        """
        Build workflow directly from vector store analysis with specific nodes
        
        Args:
            analysis: AI analysis with vector store context
            workflow_name: Generated workflow name
            
        Returns:
            WorkflowConfig ready for n8n
        """
        logger.info("Building enhanced custom workflow from vector analysis")
        
        # Extract specific nodes identified by AI from vector examples
        nodes_required = analysis.get("nodes_required", [])
        parameters = analysis.get("parameters", {})
        description = analysis.get("description", "AI-generated from vector examples")
        
        # Use the workflow builder's AI workflow method but with enhanced requirements
        requirements = {
            "trigger": "custom",  # Use custom handling
            "actions": ["process_data", "connect_services"],
            "nodes_required": nodes_required,
            "parameters": parameters,
            "enhanced_from_vector": True,  # Flag for special handling
            "keywords": self._extract_keywords_from_prompt(workflow_name)
        }
        
        logger.info(f"Building with vector-enhanced requirements: nodes={nodes_required}")
        
        return self.workflow_builder.build_ai_workflow(
            workflow_name,
            description,
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
            
            # Get the full n8n workflow JSON from the created workflow
            full_workflow = n8n_workflow.copy()
            
            # Add our metadata to the full workflow
            full_workflow.update({
                "description": request.description or "",
                "template_used": request.template_id,
                "url": f"{self.n8n_client.base_url}/workflow/{workflow_id}",
                "ai_generated": False
            })
            
            return {
                "success": True,
                "workflow": full_workflow,
                "metadata": {
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
            # Add authentication headers for external Ollama server
            import os
            api_key = os.getenv("OLLAMA_API_KEY", "key")
            headers = {"Authorization": f"Bearer {api_key}"} if api_key != "key" else {}
            response = requests.get(f"{self.ollama_url}/api/tags", headers=headers, timeout=10)
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