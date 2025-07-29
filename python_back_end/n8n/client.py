"""
n8n REST API Client

Handles authentication and communication with the n8n REST API for workflow CRUD operations.
"""

import os
import json
import requests
import logging
from typing import Dict, List, Optional, Any
from requests.auth import HTTPBasicAuth
from requests.exceptions import RequestException, HTTPError

logger = logging.getLogger(__name__)


class N8nClientError(Exception):
    """Custom exception for n8n client errors"""
    pass


class N8nClient:
    """
    Client for interacting with n8n REST API
    
    Handles authentication, workflow CRUD operations, and error handling
    for programmatic n8n workflow management.
    """
    
    def __init__(self, 
                 base_url: str = None,
                 username: str = None, 
                 password: str = None,
                 api_key: str = None,
                 timeout: int = 30):
        """
        Initialize n8n client
        
        Args:
            base_url: n8n server URL (defaults to docker network URL)
            username: Username for login (will be treated as email if contains @)
            password: Password for login
            api_key: n8n API key JWT token (preferred method)
            timeout: Request timeout in seconds
        """
        self.base_url = base_url or os.getenv("N8N_URL", "http://n8n:5678")
        self.api_key = api_key or os.getenv("N8N_API_KEY")
        self.username = username or os.getenv("N8N_USER", "admin")
        self.password = password or os.getenv("N8N_PASSWORD", "adminpass")
        self.timeout = timeout
        
        # Ensure base URL doesn't end with slash
        self.base_url = self.base_url.rstrip('/')
        
        # Set up session for authentication
        self.session = requests.Session()
        self.session.timeout = timeout
        self.authenticated = False
        
        logger.info(f"Initialized n8n client for {self.base_url} with session auth user: {self.username}")
    
    def _login(self) -> bool:
        """
        Authenticate with n8n using API key
        
        Returns:
            True if authentication successful, False otherwise
        """
        if self.authenticated:
            return True

        if not self.api_key:
            raise N8nClientError("API key not provided. Set N8N_API_KEY environment variable or pass api_key parameter.")

        # Test the API key
        try:
            headers = {'X-N8N-API-KEY': self.api_key}
            test_url = f"{self.base_url}/api/v1/workflows"
            response = self.session.get(test_url, headers=headers, timeout=self.timeout)
            
            if response.status_code == 200:
                self.authenticated = True
                self.use_api_v1 = True
                logger.info("✅ Successfully authenticated with API key")
                return True
            else:
                logger.error(f"❌ API key authentication failed: {response.status_code} - {response.text}")
                raise N8nClientError(f"API key authentication failed: {response.status_code} - {response.text}")
                
        except Exception as e:
            logger.error(f"❌ API key authentication error: {e}")
            raise N8nClientError(f"API key authentication error: {e}")
    
    
    def _make_request(self, method: str, endpoint: str, **kwargs) -> Dict[str, Any]:
        """
        Make authenticated request to n8n API
        
        Args:
            method: HTTP method (GET, POST, PUT, DELETE)
            endpoint: API endpoint path
            **kwargs: Additional request parameters
            
        Returns:
            JSON response as dictionary
            
        Raises:
            N8nClientError: On API errors or connection issues
        """
        # Ensure we're authenticated
        if not self._login():
            raise N8nClientError("Failed to authenticate with n8n")
            
        # Use /api/v1 for newer n8n versions, /rest for older
        api_prefix = "/api/v1" if hasattr(self, 'use_api_v1') and self.use_api_v1 else "/rest"
        url = f"{self.base_url}{api_prefix}{endpoint}"
        
        # Set default headers
        headers = kwargs.get('headers', {})
        headers.setdefault('Content-Type', 'application/json')
        
        # Add API key authentication (required)
        if not self.api_key:
            raise N8nClientError("API key is missing — cannot perform request")
        
        headers['X-N8N-API-KEY'] = self.api_key
        
        kwargs['headers'] = headers
        
        try:
            logger.info(f"Making {method} request to {url} with session authentication")
            response = self.session.request(method, url, **kwargs)
            response.raise_for_status()
            
            # Handle empty responses
            if response.status_code == 204:  # No Content
                return {}
            
            return response.json()
            
        except HTTPError as e:
            error_msg = f"n8n API error {e.response.status_code}: {e.response.text}"
            logger.error(error_msg)
            raise N8nClientError(error_msg) from e
            
        except RequestException as e:
            error_msg = f"n8n connection error: {str(e)}"
            logger.error(error_msg)
            raise N8nClientError(error_msg) from e
    
    def test_connection(self) -> bool:
        """
        Test connection and authentication to n8n
        
        Returns:
            True if connection successful, False otherwise
        """
        try:
            self.get_workflows()
            logger.info("n8n connection test successful")
            return True
        except N8nClientError:
            logger.error("n8n connection test failed")
            return False
    
    def get_workflows(self) -> List[Dict[str, Any]]:
        """
        Get all workflows
        
        Returns:
            List of workflow objects
        """
        try:
            response = self._make_request('GET', '/workflows')
            workflows = response.get('data', []) if isinstance(response, dict) else response
            logger.info(f"Retrieved {len(workflows)} workflows")
            return workflows
        except N8nClientError as e:
            logger.error(f"Failed to get workflows: {e}")
            raise
    
    def get_workflow(self, workflow_id: str) -> Dict[str, Any]:
        """
        Get specific workflow by ID
        
        Args:
            workflow_id: n8n workflow ID
            
        Returns:
            Workflow object
        """
        try:
            workflow = self._make_request('GET', f'/workflows/{workflow_id}')
            logger.info(f"Retrieved workflow {workflow_id}")
            return workflow
        except N8nClientError as e:
            logger.error(f"Failed to get workflow {workflow_id}: {e}")
            raise
    
    def _sanitize_workflow_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Remove read-only fields and fix field types in workflow payload before sending to n8n API
        
        Args:
            payload: Raw workflow payload
            
        Returns:
            Sanitized payload without read-only fields and proper field types
        """
        import uuid
        
        # Only include fields that n8n API actually accepts for workflow creation
        allowed_fields = [
            'name',
            'nodes', 
            'connections',
            'settings',
            'staticData'
        ]
        
        # Start with only allowed fields
        sanitized = {k: v for k, v in payload.items() if k in allowed_fields}
        
        # Ensure required fields exist
        if 'name' not in sanitized:
            sanitized['name'] = 'Generated Workflow'
        if 'nodes' not in sanitized:
            sanitized['nodes'] = []
        if 'connections' not in sanitized:
            sanitized['connections'] = {}
        if 'settings' not in sanitized:
            sanitized['settings'] = {}
        if 'staticData' not in sanitized:
            sanitized['staticData'] = {}
        
        # Fix node IDs - n8n expects UUIDs, not custom IDs from LLM
        if 'nodes' in sanitized:
            node_id_mapping = {}
            for node in sanitized['nodes']:
                if 'id' in node:
                    old_id = node['id']
                    new_id = str(uuid.uuid4())
                    node_id_mapping[old_id] = new_id
                    node['id'] = new_id
                    logger.debug(f"Remapped node ID: {old_id} → {new_id}")
                else:
                    node['id'] = str(uuid.uuid4())
                
                # Ensure required node fields
                if 'typeVersion' not in node:
                    node['typeVersion'] = 1
                if 'position' not in node:
                    node['position'] = [300, 300]
                if 'parameters' not in node:
                    node['parameters'] = {}
                if 'credentials' not in node:
                    node['credentials'] = {}
            
            # Fix connections to use new node IDs
            if 'connections' in sanitized:
                new_connections = {}
                for source_node, connections in sanitized['connections'].items():
                    # Update source node ID
                    new_source_id = node_id_mapping.get(source_node, source_node)
                    new_connections[new_source_id] = {}
                    
                    for output_type, outputs in connections.items():
                        new_connections[new_source_id][output_type] = []
                        # Handle nested array structure - outputs might contain another array
                        if isinstance(outputs, list) and len(outputs) > 0 and isinstance(outputs[0], list):
                            # Structure is: outputs = [[{connection}, {connection}]]
                            for output_list in outputs:
                                for connection in output_list:
                                    if isinstance(connection, dict):
                                        old_target = connection.get('node')
                                        if old_target in node_id_mapping:
                                            connection['node'] = node_id_mapping[old_target]
                                        new_connections[new_source_id][output_type].append(connection)
                                    else:
                                        logger.warning(f"Unexpected connection type: {type(connection)}, value: {connection}")
                                        new_connections[new_source_id][output_type].append(connection)
                        else:
                            # Structure is: outputs = [{connection}, {connection}]  
                            for connection in outputs:
                                if isinstance(connection, dict):
                                    old_target = connection.get('node')
                                    if old_target in node_id_mapping:
                                        connection['node'] = node_id_mapping[old_target]
                                    new_connections[new_source_id][output_type].append(connection)
                                else:
                                    logger.warning(f"Unexpected connection type: {type(connection)}, value: {connection}")
                                    new_connections[new_source_id][output_type].append(connection)
                
                sanitized['connections'] = new_connections
        
        # Log what was filtered out
        filtered_fields = [k for k in payload.keys() if k not in allowed_fields]
        if filtered_fields:
            logger.info(f"Filtered out non-allowed fields from payload: {filtered_fields}")
        
        return sanitized

    def create_workflow(self, workflow_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create new workflow
        
        Args:
            workflow_data: Workflow definition (name, nodes, connections)
            
        Returns:
            Created workflow object with ID
        """
        try:
            # Sanitize payload to remove read-only fields like 'active'
            sanitized_data = self._sanitize_workflow_payload(workflow_data)
            
            # Debug logging
            logger.info(f"Original workflow data keys: {list(workflow_data.keys())}")
            logger.info(f"Sanitized workflow data keys: {list(sanitized_data.keys())}")
            logger.debug(f"Sanitized payload structure: {json.dumps(sanitized_data, indent=2)[:2000]}")
            
            workflow = self._make_request('POST', '/workflows', json=sanitized_data)
            workflow_id = workflow.get('id', 'unknown')
            logger.info(f"Created workflow {workflow_id}: {workflow_data.get('name', 'Unnamed')}")
            return workflow
        except N8nClientError as e:
            logger.error(f"Failed to create workflow: {e}")
            raise
    
    def update_workflow(self, workflow_id: str, workflow_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update existing workflow
        
        Args:
            workflow_id: n8n workflow ID
            workflow_data: Updated workflow definition
            
        Returns:
            Updated workflow object
        """
        try:
            workflow = self._make_request('PUT', f'/workflows/{workflow_id}', json=workflow_data)
            logger.info(f"Updated workflow {workflow_id}")
            return workflow
        except N8nClientError as e:
            logger.error(f"Failed to update workflow {workflow_id}: {e}")
            raise
    
    def delete_workflow(self, workflow_id: str) -> bool:
        """
        Delete workflow
        
        Args:
            workflow_id: n8n workflow ID
            
        Returns:
            True if deleted successfully
        """
        try:
            self._make_request('DELETE', f'/workflows/{workflow_id}')
            logger.info(f"Deleted workflow {workflow_id}")
            return True
        except N8nClientError as e:
            logger.error(f"Failed to delete workflow {workflow_id}: {e}")
            raise
    
    def activate_workflow(self, workflow_id: str) -> Dict[str, Any]:
        """
        Activate/enable workflow
        
        Args:
            workflow_id: n8n workflow ID
            
        Returns:
            Updated workflow object
        """
        try:
            workflow = self._make_request('POST', f'/workflows/{workflow_id}/activate')
            logger.info(f"Activated workflow {workflow_id}")
            return workflow
        except N8nClientError as e:
            logger.error(f"Failed to activate workflow {workflow_id}: {e}")
            raise
    
    def deactivate_workflow(self, workflow_id: str) -> Dict[str, Any]:
        """
        Deactivate/disable workflow
        
        Args:
            workflow_id: n8n workflow ID
            
        Returns:
            Updated workflow object
        """
        try:
            workflow = self._make_request('POST', f'/workflows/{workflow_id}/deactivate')
            logger.info(f"Deactivated workflow {workflow_id}")
            return workflow
        except N8nClientError as e:
            logger.error(f"Failed to deactivate workflow {workflow_id}: {e}")
            raise
    
    def execute_workflow(self, workflow_id: str, data: Optional[Dict] = None) -> Dict[str, Any]:
        """
        Execute workflow manually
        
        Args:
            workflow_id: n8n workflow ID
            data: Optional input data for execution
            
        Returns:
            Execution result
        """
        try:
            payload = {"workflowData": data} if data else {}
            result = self._make_request('POST', f'/workflows/{workflow_id}/execute', json=payload)
            logger.info(f"Executed workflow {workflow_id}")
            return result
        except N8nClientError as e:
            logger.error(f"Failed to execute workflow {workflow_id}: {e}")
            raise
    
    def get_executions(self, workflow_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        """
        Get workflow execution history
        
        Args:
            workflow_id: n8n workflow ID
            limit: Maximum number of executions to return
            
        Returns:
            List of execution objects
        """
        try:
            params = {'limit': limit, 'workflowId': workflow_id}
            response = self._make_request('GET', '/executions', params=params)
            executions = response.get('data', []) if isinstance(response, dict) else response
            logger.info(f"Retrieved {len(executions)} executions for workflow {workflow_id}")
            return executions
        except N8nClientError as e:
            logger.error(f"Failed to get executions for workflow {workflow_id}: {e}")
            raise