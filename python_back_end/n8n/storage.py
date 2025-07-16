"""
n8n Workflow Database Storage

Handles PostgreSQL storage for n8n workflow metadata, templates, and automation history.
"""

import asyncpg
import logging
import json
from typing import List, Optional, Dict, Any
from datetime import datetime
from .models import WorkflowRecord, AutomationHistory

logger = logging.getLogger(__name__)


class N8nStorage:
    """
    Database storage for n8n workflow management
    
    Handles workflow metadata, templates, and automation history in PostgreSQL.
    """
    
    def __init__(self, db_pool):
        """
        Initialize storage with database pool
        
        Args:
            db_pool: asyncpg connection pool
        """
        self.db_pool = db_pool
        logger.info("Initialized n8n storage")
    
    async def ensure_tables(self):
        """Create n8n tables if they don't exist"""
        create_workflows_table = """
        CREATE TABLE IF NOT EXISTS n8n_workflows (
            id SERIAL PRIMARY KEY,
            workflow_id VARCHAR(255) UNIQUE NOT NULL,
            user_id INTEGER REFERENCES users(id),
            name VARCHAR(255) NOT NULL,
            description TEXT,
            prompt TEXT,
            template_id VARCHAR(100),
            config JSONB NOT NULL,
            status VARCHAR(50) DEFAULT 'created',
            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
        );
        """
        
        create_automation_history_table = """
        CREATE TABLE IF NOT EXISTS n8n_automation_history (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id),
            prompt TEXT NOT NULL,
            response TEXT NOT NULL,
            workflow_id VARCHAR(255),
            success BOOLEAN NOT NULL,
            error_message TEXT,
            execution_time FLOAT NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
        );
        """
        
        create_workflow_templates_table = """
        CREATE TABLE IF NOT EXISTS n8n_workflow_templates (
            id VARCHAR(100) PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            description TEXT,
            category VARCHAR(100),
            tags TEXT[],
            config JSONB NOT NULL,
            parameters JSONB,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
        );
        """
        
        # Indexes for performance
        create_indexes = [
            "CREATE INDEX IF NOT EXISTS idx_n8n_workflows_user_id ON n8n_workflows(user_id);",
            "CREATE INDEX IF NOT EXISTS idx_n8n_workflows_status ON n8n_workflows(status);",
            "CREATE INDEX IF NOT EXISTS idx_n8n_automation_history_user_id ON n8n_automation_history(user_id);",
            "CREATE INDEX IF NOT EXISTS idx_n8n_automation_history_success ON n8n_automation_history(success);",
            "CREATE INDEX IF NOT EXISTS idx_n8n_workflow_templates_category ON n8n_workflow_templates(category);"
        ]
        
        async with self.db_pool.acquire() as conn:
            try:
                await conn.execute(create_workflows_table)
                await conn.execute(create_automation_history_table)
                await conn.execute(create_workflow_templates_table)
                
                for index_sql in create_indexes:
                    await conn.execute(index_sql)
                
                logger.info("n8n database tables ensured")
            except Exception as e:
                logger.error(f"Failed to create n8n tables: {e}")
                raise
    
    # Workflow CRUD operations
    
    async def save_workflow(self, workflow_record: WorkflowRecord) -> int:
        """
        Save workflow record to database
        
        Args:
            workflow_record: WorkflowRecord to save
            
        Returns:
            Database ID of saved record
        """
        insert_sql = """
        INSERT INTO n8n_workflows (workflow_id, user_id, name, description, prompt, 
                                  template_id, config, status)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        RETURNING id;
        """
        
        async with self.db_pool.acquire() as conn:
            try:
                record_id = await conn.fetchval(
                    insert_sql,
                    workflow_record.workflow_id,
                    workflow_record.user_id,
                    workflow_record.name,
                    workflow_record.description,
                    workflow_record.prompt,
                    workflow_record.template_id,
                    json.dumps(workflow_record.config),
                    workflow_record.status
                )
                logger.info(f"Saved workflow record {record_id} for workflow {workflow_record.workflow_id}")
                return record_id
            except Exception as e:
                logger.error(f"Failed to save workflow record: {e}")
                raise
    
    async def get_workflow(self, workflow_id: str, user_id: Optional[int] = None) -> Optional[WorkflowRecord]:
        """
        Get workflow record by ID
        
        Args:
            workflow_id: n8n workflow ID
            user_id: Optional user ID filter
            
        Returns:
            WorkflowRecord or None if not found
        """
        if user_id:
            select_sql = """
            SELECT id, workflow_id, user_id, name, description, prompt, template_id, 
                   config, status, created_at, updated_at
            FROM n8n_workflows 
            WHERE workflow_id = $1 AND user_id = $2;
            """
            params = [workflow_id, user_id]
        else:
            select_sql = """
            SELECT id, workflow_id, user_id, name, description, prompt, template_id, 
                   config, status, created_at, updated_at
            FROM n8n_workflows 
            WHERE workflow_id = $1;
            """
            params = [workflow_id]
        
        async with self.db_pool.acquire() as conn:
            try:
                row = await conn.fetchrow(select_sql, *params)
                if row:
                    return WorkflowRecord(
                        id=row['id'],
                        workflow_id=row['workflow_id'],
                        user_id=row['user_id'],
                        name=row['name'],
                        description=row['description'],
                        prompt=row['prompt'],
                        template_id=row['template_id'],
                        config=row['config'],
                        status=row['status'],
                        created_at=row['created_at'],
                        updated_at=row['updated_at']
                    )
                return None
            except Exception as e:
                logger.error(f"Failed to get workflow {workflow_id}: {e}")
                raise
    
    async def list_user_workflows(self, user_id: int, limit: int = 50, 
                                 offset: int = 0) -> List[WorkflowRecord]:
        """
        List workflows for user
        
        Args:
            user_id: User ID
            limit: Maximum results
            offset: Result offset
            
        Returns:
            List of WorkflowRecord objects
        """
        select_sql = """
        SELECT id, workflow_id, user_id, name, description, prompt, template_id, 
               config, status, created_at, updated_at
        FROM n8n_workflows 
        WHERE user_id = $1
        ORDER BY created_at DESC
        LIMIT $2 OFFSET $3;
        """
        
        async with self.db_pool.acquire() as conn:
            try:
                rows = await conn.fetch(select_sql, user_id, limit, offset)
                workflows = []
                for row in rows:
                    workflows.append(WorkflowRecord(
                        id=row['id'],
                        workflow_id=row['workflow_id'],
                        user_id=row['user_id'],
                        name=row['name'],
                        description=row['description'],
                        prompt=row['prompt'],
                        template_id=row['template_id'],
                        config=row['config'],
                        status=row['status'],
                        created_at=row['created_at'],
                        updated_at=row['updated_at']
                    ))
                logger.info(f"Retrieved {len(workflows)} workflows for user {user_id}")
                return workflows
            except Exception as e:
                logger.error(f"Failed to list workflows for user {user_id}: {e}")
                raise
    
    async def update_workflow_status(self, workflow_id: str, status: str, 
                                   user_id: Optional[int] = None) -> bool:
        """
        Update workflow status
        
        Args:
            workflow_id: n8n workflow ID
            status: New status
            user_id: Optional user ID filter
            
        Returns:
            True if updated, False if not found
        """
        if user_id:
            update_sql = """
            UPDATE n8n_workflows 
            SET status = $1, updated_at = CURRENT_TIMESTAMP
            WHERE workflow_id = $2 AND user_id = $3;
            """
            params = [status, workflow_id, user_id]
        else:
            update_sql = """
            UPDATE n8n_workflows 
            SET status = $1, updated_at = CURRENT_TIMESTAMP
            WHERE workflow_id = $2;
            """
            params = [status, workflow_id]
        
        async with self.db_pool.acquire() as conn:
            try:
                result = await conn.execute(update_sql, *params)
                updated = result.split()[-1] == '1'  # Check if 1 row was updated
                if updated:
                    logger.info(f"Updated workflow {workflow_id} status to {status}")
                return updated
            except Exception as e:
                logger.error(f"Failed to update workflow {workflow_id} status: {e}")
                raise
    
    async def delete_workflow(self, workflow_id: str, user_id: Optional[int] = None) -> bool:
        """
        Delete workflow record
        
        Args:
            workflow_id: n8n workflow ID
            user_id: Optional user ID filter
            
        Returns:
            True if deleted, False if not found
        """
        if user_id:
            delete_sql = "DELETE FROM n8n_workflows WHERE workflow_id = $1 AND user_id = $2;"
            params = [workflow_id, user_id]
        else:
            delete_sql = "DELETE FROM n8n_workflows WHERE workflow_id = $1;"
            params = [workflow_id]
        
        async with self.db_pool.acquire() as conn:
            try:
                result = await conn.execute(delete_sql, *params)
                deleted = result.split()[-1] == '1'  # Check if 1 row was deleted
                if deleted:
                    logger.info(f"Deleted workflow record {workflow_id}")
                return deleted
            except Exception as e:
                logger.error(f"Failed to delete workflow {workflow_id}: {e}")
                raise
    
    # Automation history operations
    
    async def save_automation_history(self, history: AutomationHistory) -> int:
        """
        Save automation request history
        
        Args:
            history: AutomationHistory record
            
        Returns:
            Database ID of saved record
        """
        insert_sql = """
        INSERT INTO n8n_automation_history (user_id, prompt, response, workflow_id, 
                                           success, error_message, execution_time)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        RETURNING id;
        """
        
        async with self.db_pool.acquire() as conn:
            try:
                record_id = await conn.fetchval(
                    insert_sql,
                    history.user_id,
                    history.prompt,
                    history.response,
                    history.workflow_id,
                    history.success,
                    history.error_message,
                    history.execution_time
                )
                logger.info(f"Saved automation history {record_id}")
                return record_id
            except Exception as e:
                logger.error(f"Failed to save automation history: {e}")
                raise
    
    async def get_automation_history(self, user_id: int, limit: int = 50, 
                                   offset: int = 0) -> List[AutomationHistory]:
        """
        Get automation history for user
        
        Args:
            user_id: User ID
            limit: Maximum results
            offset: Result offset
            
        Returns:
            List of AutomationHistory records
        """
        select_sql = """
        SELECT id, user_id, prompt, response, workflow_id, success, 
               error_message, execution_time, created_at
        FROM n8n_automation_history 
        WHERE user_id = $1
        ORDER BY created_at DESC
        LIMIT $2 OFFSET $3;
        """
        
        async with self.db_pool.acquire() as conn:
            try:
                rows = await conn.fetch(select_sql, user_id, limit, offset)
                history = []
                for row in rows:
                    history.append(AutomationHistory(
                        id=row['id'],
                        user_id=row['user_id'],
                        prompt=row['prompt'],
                        response=row['response'],
                        workflow_id=row['workflow_id'],
                        success=row['success'],
                        error_message=row['error_message'],
                        execution_time=row['execution_time'],
                        created_at=row['created_at']
                    ))
                logger.info(f"Retrieved {len(history)} automation history records for user {user_id}")
                return history
            except Exception as e:
                logger.error(f"Failed to get automation history for user {user_id}: {e}")
                raise
    
    # Template operations
    
    async def save_template(self, template_data: Dict[str, Any]) -> str:
        """
        Save workflow template
        
        Args:
            template_data: Template configuration
            
        Returns:
            Template ID
        """
        insert_sql = """
        INSERT INTO n8n_workflow_templates (id, name, description, category, tags, config, parameters)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        ON CONFLICT (id) DO UPDATE SET
            name = EXCLUDED.name,
            description = EXCLUDED.description,
            category = EXCLUDED.category,
            tags = EXCLUDED.tags,
            config = EXCLUDED.config,
            parameters = EXCLUDED.parameters,
            updated_at = CURRENT_TIMESTAMP
        RETURNING id;
        """
        
        async with self.db_pool.acquire() as conn:
            try:
                template_id = await conn.fetchval(
                    insert_sql,
                    template_data['id'],
                    template_data['name'],
                    template_data.get('description'),
                    template_data.get('category'),
                    template_data.get('tags', []),
                    json.dumps(template_data['config']),
                    json.dumps(template_data.get('parameters', []))
                )
                logger.info(f"Saved template {template_id}")
                return template_id
            except Exception as e:
                logger.error(f"Failed to save template: {e}")
                raise
    
    async def get_templates(self, category: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get workflow templates
        
        Args:
            category: Optional category filter
            
        Returns:
            List of template dictionaries
        """
        if category:
            select_sql = """
            SELECT id, name, description, category, tags, config, parameters, created_at, updated_at
            FROM n8n_workflow_templates
            WHERE category = $1
            ORDER BY name;
            """
            params = [category]
        else:
            select_sql = """
            SELECT id, name, description, category, tags, config, parameters, created_at, updated_at
            FROM n8n_workflow_templates
            ORDER BY category, name;
            """
            params = []
        
        async with self.db_pool.acquire() as conn:
            try:
                rows = await conn.fetch(select_sql, *params)
                templates = []
                for row in rows:
                    templates.append({
                        'id': row['id'],
                        'name': row['name'],
                        'description': row['description'],
                        'category': row['category'],
                        'tags': row['tags'],
                        'config': row['config'],
                        'parameters': row['parameters'],
                        'created_at': row['created_at'],
                        'updated_at': row['updated_at']
                    })
                logger.info(f"Retrieved {len(templates)} templates")
                return templates
            except Exception as e:
                logger.error(f"Failed to get templates: {e}")
                raise