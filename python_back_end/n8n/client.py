"""
n8n REST API Client

Handles authentication and communication with the n8n REST API for workflow CRUD operations.
"""

import os
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
            username: Basic auth username (optional if using API key)
            password: Basic auth password (optional if using API key)
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
        
        # Set up authentication - prefer API key over basic auth
        if self.api_key:
            self.auth = None  # Will use Bearer token in headers
            self.auth_method = "bearer"
            logger.info(f"Initialized n8n client for {self.base_url} with API key authentication")
        else:
            self.auth = HTTPBasicAuth(self.username, self.password)
            self.auth_method = "basic"
            logger.info(f"Initialized n8n client for {self.base_url} with basic auth user: {self.username}")
    
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
        url = f"{self.base_url}/rest{endpoint}"
        
        # Set default headers
        headers = kwargs.get('headers', {})
        headers.setdefault('Content-Type', 'application/json')
        
        # Add authentication
        if self.auth_method == "bearer" and self.api_key:
            headers['Authorization'] = f'Bearer {self.api_key}'
        elif self.auth_method == "basic" and self.auth:
            kwargs['auth'] = self.auth
        
        kwargs['headers'] = headers
        kwargs['timeout'] = self.timeout
        
        try:
            logger.info(f"Making {method} request to {url} with {self.auth_method} authentication")
            if self.auth_method == "bearer":
                logger.info(f"Using API key: {self.api_key[:20]}..." if self.api_key else "No API key found")
            else:
                logger.info(f"Using basic auth: {self.username}:{self.password}")
            response = requests.request(method, url, **kwargs)
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
    
    def create_workflow(self, workflow_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create new workflow
        
        Args:
            workflow_data: Workflow definition (name, nodes, connections)
            
        Returns:
            Created workflow object with ID
        """
        try:
            workflow = self._make_request('POST', '/workflows', json=workflow_data)
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