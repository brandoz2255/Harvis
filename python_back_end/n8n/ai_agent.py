"""
AI Agent for n8n automation with vector database integration

This module provides enhanced AI agents that can use vector search to find
relevant workflow examples and create better n8n automations.
"""

import logging
import asyncio
from typing import Dict, Any, List, Optional
from .vector_db import get_vector_db_service, VectorDatabaseService
from .automation_service import N8nAutomationService
from .models import N8nAutomationRequest

logger = logging.getLogger(__name__)

class N8nAIAgent:
    """
    Enhanced AI agent for n8n automation with vector database capabilities
    """
    
    def __init__(self, automation_service: N8nAutomationService):
        """
        Initialize the AI agent
        
        Args:
            automation_service: N8n automation service instance
        """
        self.automation_service = automation_service
        self.vector_db: VectorDatabaseService = get_vector_db_service()
        
    async def initialize(self):
        """Initialize the AI agent and vector database"""
        try:
            await self.vector_db.initialize()
            logger.info("✅ N8nAIAgent initialized successfully")
        except Exception as e:
            logger.error(f"❌ Failed to initialize N8nAIAgent: {e}")
            raise
    
    async def process_automation_request_with_context(
        self, 
        request: N8nAutomationRequest,
        user_id: int
    ) -> Dict[str, Any]:
        """
        Process automation request with vector database context
        
        Args:
            request: N8n automation request
            user_id: User ID making the request
            
        Returns:
            Enhanced automation result with context
        """
        try:
            logger.info(f"🤖 Processing automation request with AI context: {request.prompt[:100]}...")
            
            # Step 1: Search for similar workflows in vector database
            context_data = await self.vector_db.get_workflow_suggestions(
                user_request=request.prompt,
                context_limit=3
            )
            
            # Step 2: Enhance the original prompt with context
            enhanced_prompt = self._enhance_prompt_with_context(request.prompt, context_data)
            
            # Step 3: Create enhanced request
            enhanced_request = N8nAutomationRequest(
                prompt=enhanced_prompt,
                model=request.model,
                session_id=request.session_id,
                user_context=request.user_context
            )
            
            # Step 4: Process with automation service
            result = await self.automation_service.process_automation_request(
                enhanced_request, 
                user_id=user_id
            )
            
            # Step 5: Enhance result with context information
            if result.get("success"):
                result["ai_context"] = {
                    "similar_workflows_found": len(context_data.get("similar_workflows", [])),
                    "context_used": bool(context_data.get("similar_workflows")),
                    "suggestions": context_data.get("suggestions", []),
                    "vector_search_query": request.prompt
                }
                
                # Add workflow to vector database for future reference
                await self._add_created_workflow_to_vector_db(result["workflow"], user_id)
            
            return result
            
        except Exception as e:
            logger.error(f"❌ Error processing automation request with context: {e}")
            return {
                "success": False,
                "error": f"AI agent processing failed: {str(e)}",
                "fallback_used": True
            }
    
    def _enhance_prompt_with_context(
        self, 
        original_prompt: str, 
        context_data: Dict[str, Any]
    ) -> str:
        """
        Enhance the original prompt with vector database context
        
        Args:
            original_prompt: User's original automation request
            context_data: Context from vector database search
            
        Returns:
            Enhanced prompt with context
        """
        similar_workflows = context_data.get("similar_workflows", [])
        
        if not similar_workflows:
            return original_prompt
        
        # Build enhanced prompt
        enhanced_parts = [
            f"User Request: {original_prompt}",
            "",
            "Similar Workflow Examples for Reference:",
        ]
        
        for i, workflow in enumerate(similar_workflows[:3], 1):
            metadata = workflow.get("metadata", {})
            content = workflow.get("content", "")
            score = workflow.get("similarity_score", 0)
            
            workflow_name = metadata.get("workflow_name", f"Example {i}")
            node_types = metadata.get("node_types", [])
            
            enhanced_parts.extend([
                f"{i}. {workflow_name} (similarity: {score:.3f})",
                f"   Nodes used: {', '.join(node_types[:5]) if node_types else 'N/A'}",
                f"   Description: {content[:150]}...",
                ""
            ])
        
        enhanced_parts.extend([
            "Instructions:",
            "- Use the above examples as inspiration for creating the requested workflow",
            "- Adapt the node types and patterns that are most relevant",
            "- Create a new workflow that fulfills the user's specific requirements",
            f"- Original request: {original_prompt}"
        ])
        
        return "\n".join(enhanced_parts)
    
    async def _add_created_workflow_to_vector_db(
        self, 
        workflow_data: Dict[str, Any], 
        user_id: int
    ) -> bool:
        """
        Add the newly created workflow to vector database for future reference
        
        Args:
            workflow_data: Created workflow data
            user_id: User who created the workflow
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Extract workflow information
            workflow_name = workflow_data.get("name", "Unnamed Workflow")
            workflow_description = workflow_data.get("description", "")
            nodes = workflow_data.get("nodes", [])
            
            # Extract node types
            node_types = []
            for node in nodes:
                node_type = node.get("type", "")
                if node_type and node_type not in node_types:
                    node_types.append(node_type)
            
            # Create content for vector storage
            content_parts = [
                f"Workflow: {workflow_name}",
                f"Description: {workflow_description}",
                f"Node types: {', '.join(node_types)}",
                f"Total nodes: {len(nodes)}"
            ]
            
            # Add node details
            for node in nodes[:5]:  # Limit to first 5 nodes
                node_name = node.get("name", "")
                node_type = node.get("type", "")
                if node_name and node_type:
                    content_parts.append(f"- {node_name} ({node_type})")
            
            content = "\n".join(content_parts)
            
            # Metadata for the workflow
            metadata = {
                "workflow_name": workflow_name,
                "workflow_id": workflow_data.get("id", ""),
                "user_id": user_id,
                "node_types": node_types,
                "node_count": len(nodes),
                "created_by": "ai_agent",
                "workflow_tags": workflow_data.get("tags", [])
            }
            
            # Add to vector database
            success = await self.vector_db.add_workflow_context(
                content=content,
                metadata=metadata,
                source_repo="ai_created_workflows"
            )
            
            if success:
                logger.info(f"✅ Added created workflow '{workflow_name}' to vector database")
            
            return success
            
        except Exception as e:
            logger.error(f"❌ Error adding workflow to vector database: {e}")
            return False
    
    async def search_workflow_examples(
        self, 
        query: str, 
        limit: int = 5
    ) -> Dict[str, Any]:
        """
        Search for workflow examples in the vector database
        
        Args:
            query: Search query
            limit: Maximum number of results
            
        Returns:
            Search results with metadata
        """
        try:
            results = await self.vector_db.search_similar_workflows(
                query=query,
                k=limit,
                include_scores=True
            )
            
            return {
                "success": True,
                "query": query,
                "results": results,
                "count": len(results)
            }
            
        except Exception as e:
            logger.error(f"❌ Error searching workflow examples: {e}")
            return {
                "success": False,
                "error": str(e),
                "query": query,
                "results": [],
                "count": 0
            }
    
    async def get_workflow_insights(
        self, 
        workflow_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Get insights about a workflow using vector database
        
        Args:
            workflow_data: Workflow data to analyze
            
        Returns:
            Insights and suggestions
        """
        try:
            workflow_name = workflow_data.get("name", "Unnamed")
            nodes = workflow_data.get("nodes", [])
            node_types = [node.get("type", "") for node in nodes if node.get("type")]
            
            # Search for similar workflows
            search_query = f"{workflow_name} {' '.join(node_types[:5])}"
            similar_workflows = await self.vector_db.search_similar_workflows(
                query=search_query,
                k=3,
                include_scores=True
            )
            
            # Generate insights
            insights = {
                "workflow_name": workflow_name,
                "node_count": len(nodes),
                "unique_node_types": len(set(node_types)),
                "node_types": list(set(node_types)),
                "similar_workflows": similar_workflows,
                "suggestions": []
            }
            
            # Add suggestions based on similar workflows
            if similar_workflows:
                insights["suggestions"].append(
                    f"Found {len(similar_workflows)} similar workflows for reference"
                )
                
                # Collect common node types from similar workflows
                common_nodes = set()
                for workflow in similar_workflows:
                    metadata = workflow.get("metadata", {})
                    similar_node_types = metadata.get("node_types", [])
                    common_nodes.update(similar_node_types)
                
                missing_common_nodes = common_nodes - set(node_types)
                if missing_common_nodes:
                    insights["suggestions"].append(
                        f"Consider adding these common nodes: {', '.join(list(missing_common_nodes)[:3])}"
                    )
            
            return insights
            
        except Exception as e:
            logger.error(f"❌ Error getting workflow insights: {e}")
            return {
                "error": str(e),
                "workflow_name": workflow_data.get("name", "Unknown"),
                "suggestions": ["Error analyzing workflow"]
            }
    
    async def health_check(self) -> Dict[str, Any]:
        """Check the health of the AI agent"""
        try:
            # Check vector database health
            vector_health = await self.vector_db.health_check()
            
            # Check automation service health (if it exists)
            automation_health = {"status": "unknown"}
            if hasattr(self.automation_service, 'test_connection'):
                automation_health = await self.automation_service.test_connection()
            
            overall_healthy = (
                vector_health.get("status") == "healthy" and
                automation_health.get("overall_health", False)
            )
            
            return {
                "status": "healthy" if overall_healthy else "degraded",
                "vector_database": vector_health,
                "automation_service": automation_health,
                "overall_health": overall_healthy
            }
            
        except Exception as e:
            logger.error(f"❌ AI agent health check failed: {e}")
            return {
                "status": "unhealthy",
                "error": str(e),
                "overall_health": False
            }

# Global AI agent instance
_ai_agent = None

def get_ai_agent(automation_service: N8nAutomationService) -> N8nAIAgent:
    """Get the global AI agent instance"""
    global _ai_agent
    if _ai_agent is None:
        _ai_agent = N8nAIAgent(automation_service)
    return _ai_agent

async def initialize_ai_agent(automation_service: N8nAutomationService) -> N8nAIAgent:
    """Initialize the global AI agent"""
    agent = get_ai_agent(automation_service)
    await agent.initialize()
    return agent