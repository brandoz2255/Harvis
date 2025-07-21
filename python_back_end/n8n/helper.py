"""
n8n Authentication Helper Module

Simplified helper for n8n authentication supporting both API Key and Basic Auth.
This module provides a minimal interface for common n8n automation tasks.
"""

import requests
import base64
import logging
import os
from typing import Dict, List, Optional, Any, Union

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("n8n_auth_helper")

class N8NAuthHelper:
    """
    Simplified n8n authentication helper for common automation tasks.
    
    Supports both API Key authentication and Basic Authentication.
    Automatically configures for Docker network communication.
    """
    
    def __init__(self, 
                 base_url: str = None,
                 api_key: str = None, 
                 username: str = None, 
                 password: str = None,
                 timeout: int = 30):
        """
        Initialize n8n authentication helper
        
        Args:
            base_url: n8n server URL (defaults to Docker network URL)
            api_key: n8n API key for authentication (preferred)
            username: Username for Basic Auth
            password: Password for Basic Auth
            timeout: Request timeout in seconds
        """
        self.base_url = (base_url or 
                        os.getenv("N8N_URL", "http://n8n:5678")).rstrip('/')
        self.api_key = api_key or os.getenv("N8N_API_KEY")
        self.username = username or os.getenv("N8N_USER", "admin")
        self.password = password or os.getenv("N8N_PASSWORD", "adminpass")
        self.timeout = timeout
        
        logger.info(f"Initialized n8n helper for {self.base_url}")
        
        # Log authentication method
        if self.api_key:
            logger.info("Using API Key authentication")
        elif self.username and self.password:
            logger.info("Using Basic Authentication")
        else:
            logger.warning("No authentication credentials provided")

    def _get_headers(self) -> Dict[str, str]:
        """
        Generate authentication headers based on available credentials
        
        Returns:
            Dictionary of HTTP headers for authentication
        """
        headers = {
            'Content-Type': 'application/json',
            'User-Agent': 'n8n-auth-helper/1.0'
        }
        
        if self.api_key:
            # n8n API Key authentication
            headers["X-N8N-API-KEY"] = self.api_key
            logger.debug("Using API Key authentication headers")
        elif self.username and self.password:
            # Basic Authentication
            credentials = base64.b64encode(
                f"{self.username}:{self.password}".encode()
            ).decode()
            headers["Authorization"] = f"Basic {credentials}"
            logger.debug("Using Basic Authentication headers")
        
        return headers

    def test_connection(self) -> bool:
        """
        Test connection and authentication to n8n
        
        Returns:
            True if connection and authentication successful, False otherwise
        """
        try:
            response = self.get("/api/v1/workflows")
            logger.info("n8n connection test successful")
            return True
        except Exception as e:
            logger.error(f"n8n connection test failed: {e}")
            return False

    def get(self, endpoint: str, params: Optional[Dict] = None) -> Union[Dict, List]:
        """
        Perform GET request to n8n API
        
        Args:
            endpoint: API endpoint path (e.g., "/api/v1/workflows")
            params: Optional query parameters
            
        Returns:
            JSON response data
            
        Raises:
            requests.RequestException: On request failure
        """
        url = f"{self.base_url}{endpoint}"
        headers = self._get_headers()
        
        logger.debug(f"GET {url}")
        
        try:
            response = requests.get(
                url, 
                headers=headers, 
                params=params,
                timeout=self.timeout
            )
            response.raise_for_status()
            
            logger.info(f"GET {endpoint} -> {response.status_code}")
            return response.json()
            
        except requests.RequestException as e:
            logger.error(f"GET {endpoint} failed: {e}")
            raise

    def post(self, endpoint: str, data: Optional[Dict] = None) -> Union[Dict, List]:
        """
        Perform POST request to n8n API
        
        Args:
            endpoint: API endpoint path
            data: JSON data to send in request body
            
        Returns:
            JSON response data
            
        Raises:
            requests.RequestException: On request failure
        """
        url = f"{self.base_url}{endpoint}"
        headers = self._get_headers()
        
        logger.debug(f"POST {url} with data: {data}")
        
        try:
            response = requests.post(
                url, 
                headers=headers, 
                json=data,
                timeout=self.timeout
            )
            response.raise_for_status()
            
            logger.info(f"POST {endpoint} -> {response.status_code}")
            return response.json()
            
        except requests.RequestException as e:
            logger.error(f"POST {endpoint} failed: {e}")
            raise

    def put(self, endpoint: str, data: Optional[Dict] = None) -> Union[Dict, List]:
        """
        Perform PUT request to n8n API
        
        Args:
            endpoint: API endpoint path
            data: JSON data to send in request body
            
        Returns:
            JSON response data
            
        Raises:
            requests.RequestException: On request failure
        """
        url = f"{self.base_url}{endpoint}"
        headers = self._get_headers()
        
        logger.debug(f"PUT {url} with data: {data}")
        
        try:
            response = requests.put(
                url, 
                headers=headers, 
                json=data,
                timeout=self.timeout
            )
            response.raise_for_status()
            
            logger.info(f"PUT {endpoint} -> {response.status_code}")
            return response.json()
            
        except requests.RequestException as e:
            logger.error(f"PUT {endpoint} failed: {e}")
            raise

    def delete(self, endpoint: str) -> bool:
        """
        Perform DELETE request to n8n API
        
        Args:
            endpoint: API endpoint path
            
        Returns:
            True if deletion successful
            
        Raises:
            requests.RequestException: On request failure
        """
        url = f"{self.base_url}{endpoint}"
        headers = self._get_headers()
        
        logger.debug(f"DELETE {url}")
        
        try:
            response = requests.delete(
                url, 
                headers=headers,
                timeout=self.timeout
            )
            response.raise_for_status()
            
            logger.info(f"DELETE {endpoint} -> {response.status_code}")
            return True
            
        except requests.RequestException as e:
            logger.error(f"DELETE {endpoint} failed: {e}")
            raise

    # Convenience methods for common n8n operations
    
    def get_workflows(self) -> List[Dict]:
        """Get all workflows"""
        return self.get("/api/v1/workflows")
    
    def get_workflow(self, workflow_id: str) -> Dict:
        """Get specific workflow by ID"""
        return self.get(f"/api/v1/workflows/{workflow_id}")
    
    def create_workflow(self, workflow_data: Dict) -> Dict:
        """Create new workflow"""
        return self.post("/api/v1/workflows", workflow_data)
    
    def update_workflow(self, workflow_id: str, workflow_data: Dict) -> Dict:
        """Update existing workflow"""
        return self.put(f"/api/v1/workflows/{workflow_id}", workflow_data)
    
    def delete_workflow(self, workflow_id: str) -> bool:
        """Delete workflow"""
        return self.delete(f"/api/v1/workflows/{workflow_id}")
    
    def activate_workflow(self, workflow_id: str) -> Dict:
        """Activate/enable workflow"""
        return self.post(f"/api/v1/workflows/{workflow_id}/activate")
    
    def deactivate_workflow(self, workflow_id: str) -> Dict:
        """Deactivate/disable workflow"""
        return self.post(f"/api/v1/workflows/{workflow_id}/deactivate")
    
    def trigger_webhook(self, webhook_path: str, data: Optional[Dict] = None) -> Dict:
        """
        Trigger n8n webhook
        
        Args:
            webhook_path: Webhook path (e.g., "webhook/my-workflow")
            data: Data to send to webhook
            
        Returns:
            Webhook response
        """
        endpoint = f"/{webhook_path.lstrip('/')}"
        return self.post(endpoint, data)
    
    def get_executions(self, workflow_id: str = None, limit: int = 20) -> List[Dict]:
        """
        Get workflow execution history
        
        Args:
            workflow_id: Optional workflow ID to filter by
            limit: Maximum number of executions to return
            
        Returns:
            List of executions
        """
        params = {'limit': limit}
        if workflow_id:
            params['workflowId'] = workflow_id
        
        return self.get("/api/v1/executions", params)


# Example usage and factory functions

def create_n8n_client_with_api_key(api_key: str, base_url: str = None) -> N8NAuthHelper:
    """
    Create n8n client using API Key authentication
    
    Args:
        api_key: n8n API Key
        base_url: Optional n8n server URL
        
    Returns:
        Configured N8NAuthHelper instance
    """
    return N8NAuthHelper(base_url=base_url, api_key=api_key)


def create_n8n_client_with_basic_auth(username: str, password: str, base_url: str = None) -> N8NAuthHelper:
    """
    Create n8n client using Basic Authentication
    
    Args:
        username: n8n username
        password: n8n password  
        base_url: Optional n8n server URL
        
    Returns:
        Configured N8NAuthHelper instance
    """
    return N8NAuthHelper(base_url=base_url, username=username, password=password)


def create_n8n_client_from_env() -> N8NAuthHelper:
    """
    Create n8n client using environment variables
    
    Environment variables:
        N8N_URL: n8n server URL (default: http://n8n:5678)
        N8N_API_KEY: n8n API key (preferred)
        N8N_USER: n8n username (fallback: admin)
        N8N_PASSWORD: n8n password (fallback: adminpass)
        
    Returns:
        Configured N8NAuthHelper instance
    """
    return N8NAuthHelper()


# Example usage documentation
if __name__ == "__main__":
    # Example 1: API Key Authentication
    print("Example 1: API Key Authentication")
    try:
        n8n_api = create_n8n_client_with_api_key("your-api-key-here")
        workflows = n8n_api.get_workflows()
        print(f"Found {len(workflows)} workflows")
    except Exception as e:
        print(f"API Key auth failed: {e}")
    
    # Example 2: Basic Authentication
    print("\nExample 2: Basic Authentication")
    try:
        n8n_basic = create_n8n_client_with_basic_auth("admin", "adminpass")
        if n8n_basic.test_connection():
            print("Basic auth connection successful")
        else:
            print("Basic auth connection failed")
    except Exception as e:
        print(f"Basic auth failed: {e}")
    
    # Example 3: Environment Variables
    print("\nExample 3: Environment Variables")
    try:
        n8n_env = create_n8n_client_from_env()
        executions = n8n_env.get_executions(limit=5)
        print(f"Found {len(executions)} recent executions")
    except Exception as e:
        print(f"Environment auth failed: {e}")