import json
import logging
import psycopg2
import psycopg2.extras
from pgvector.psycopg2 import register_vector
import numpy as np
from typing import Dict, Any, List, Optional, Tuple
from sentence_transformers import SentenceTransformer
from dataclasses import dataclass
import hashlib
import re

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@dataclass
class VectorSearchConfig:
    """Configuration for vector search optimization"""
    similarity_threshold: float
    max_examples: int
    use_hybrid_search: bool
    rerank_results: bool
    chunk_examples: bool

class EnhancedVectorOptimizer:
    """Enhanced vector database optimizer for n8n automations with pgvector"""
    
    def __init__(self, 
                 db_conn_string: str = "postgresql://pguser:pgpassword@pgsql-db:5432/database",
                 embedding_model: str = "all-MiniLM-L6-v2",
                 table_name: str = "n8n_automations"):
        
        self.conn = psycopg2.connect(db_conn_string)
        register_vector(self.conn)
        self.embedder = SentenceTransformer(embedding_model)
        
        # Validate table name to prevent SQL injection
        if not self._is_valid_table_name(table_name):
            raise ValueError(f"Invalid table name: {table_name}")
        self.table_name = table_name
        
        # Optimization configurations for different scenarios
        self.search_configs = {
            'small_model_simple': VectorSearchConfig(
                similarity_threshold=0.75,
                max_examples=2,
                use_hybrid_search=True,
                rerank_results=True,
                chunk_examples=True
            ),
            'small_model_complex': VectorSearchConfig(
                similarity_threshold=0.65,
                max_examples=3,
                use_hybrid_search=True,
                rerank_results=True,
                chunk_examples=True
            ),
            'medium_model': VectorSearchConfig(
                similarity_threshold=0.70,
                max_examples=3,
                use_hybrid_search=True,
                rerank_results=False,
                chunk_examples=False
            ),
            'large_model': VectorSearchConfig(
                similarity_threshold=0.65,
                max_examples=4,
                use_hybrid_search=False,
                rerank_results=False,
                chunk_examples=False
            )
        }
        
        logger.info(f"Enhanced vector optimizer initialized with {embedding_model}")
    
    def analyze_request_for_search_strategy(self, request: str, model_size: str) -> str:
        """Analyze request to determine optimal search strategy"""
        
        complexity_indicators = {
            'simple': ['webhook', 'email', 'send', 'basic', 'simple'],
            'complex': ['multiple', 'condition', 'database', 'schedule', 'loop', 'complex']
        }
        
        request_lower = request.lower()
        is_complex = any(indicator in request_lower for indicator in complexity_indicators['complex'])
        
        if model_size == 'small':
            return 'small_model_complex' if is_complex else 'small_model_simple'
        else:
            return f'{model_size}_model'
    
    def extract_automation_features_enhanced(self, automation: Dict[str, Any]) -> Dict[str, Any]:
        """Enhanced feature extraction with better categorization"""
        
        nodes = automation.get('nodes', [])
        connections = automation.get('connections', {})
        
        # Enhanced node analysis
        node_types = [n.get('type', '') for n in nodes]
        node_names = [n.get('name', '') for n in nodes]
        
        # Trigger analysis
        trigger_nodes = [n for n in nodes if self._is_trigger_node(n)]
        trigger_info = {
            'type': trigger_nodes[0].get('type', 'manual') if trigger_nodes else 'manual',
            'has_webhook': any('webhook' in t.lower() for t in node_types),
            'has_schedule': any('cron' in t.lower() or 'schedule' in t.lower() for t in node_types)
        }
        
        # Action analysis
        action_types = self._categorize_actions(node_types)
        
        # Flow pattern analysis
        flow_pattern = self._analyze_flow_pattern(connections, nodes)
        
        # Complexity scoring
        complexity_metrics = {
            'node_count': len(nodes),
            'connection_count': len(connections),
            'conditional_nodes': sum(1 for t in node_types if 'if' in t.lower() or 'switch' in t.lower()),
            'loop_nodes': sum(1 for t in node_types if 'loop' in t.lower() or 'split' in t.lower()),
            'api_nodes': sum(1 for t in node_types if 'http' in t.lower() or 'api' in t.lower()),
            'database_nodes': sum(1 for t in node_types if any(db in t.lower() for db in ['mysql', 'postgres', 'mongo']))
        }
        
        complexity_score = (
            complexity_metrics['node_count'] * 2 +
            complexity_metrics['connection_count'] * 3 +
            complexity_metrics['conditional_nodes'] * 5 +
            complexity_metrics['loop_nodes'] * 4 +
            complexity_metrics['api_nodes'] * 2 +
            complexity_metrics['database_nodes'] * 3
        )
        
        return {
            'automation_id': automation.get('id', self._generate_id(automation)),
            'name': automation.get('name', 'Unnamed Automation'),
            'trigger_info': trigger_info,
            'action_types': action_types,
            'flow_pattern': flow_pattern,
            'complexity_score': complexity_score,
            'complexity_metrics': complexity_metrics,
            'node_types': node_types,
            'searchable_keywords': self._extract_searchable_keywords(automation)
        }
    
    def _is_trigger_node(self, node: Dict[str, Any]) -> bool:
        """Check if node is a trigger node"""
        node_type = node.get('type', '').lower()
        return (
            'trigger' in node_type or
            'webhook' in node_type or
            'cron' in node_type or
            'schedule' in node_type or
            'manual' in node_type
        )
    
    def _categorize_actions(self, node_types: List[str]) -> Dict[str, int]:
        """Categorize action nodes"""
        categories = {
            'data_processing': 0,
            'api_calls': 0,
            'database_operations': 0,
            'notifications': 0,
            'file_operations': 0,
            'conditionals': 0,
            'loops': 0
        }
        
        for node_type in node_types:
            node_lower = node_type.lower()
            
            if any(term in node_lower for term in ['json', 'xml', 'csv', 'transform', 'set', 'function']):
                categories['data_processing'] += 1
            elif any(term in node_lower for term in ['http', 'api', 'rest', 'webhook']):
                categories['api_calls'] += 1
            elif any(term in node_lower for term in ['mysql', 'postgres', 'mongo', 'redis', 'database']):
                categories['database_operations'] += 1
            elif any(term in node_lower for term in ['email', 'slack', 'discord', 'notification']):
                categories['notifications'] += 1
            elif any(term in node_lower for term in ['file', 'ftp', 'sftp', 's3', 'upload', 'download']):
                categories['file_operations'] += 1
            elif any(term in node_lower for term in ['if', 'switch', 'condition']):
                categories['conditionals'] += 1
            elif any(term in node_lower for term in ['loop', 'split', 'merge']):
                categories['loops'] += 1
        
        return categories
    
    def _analyze_flow_pattern(self, connections: Dict[str, Any], nodes: List[Dict[str, Any]]) -> str:
        """Analyze workflow flow pattern"""
        if not connections:
            return 'single_node'
        
        connection_count = sum(len(v.get('main', [])) for v in connections.values())
        node_count = len(nodes)
        
        if connection_count <= 1:
            return 'linear'
        elif connection_count == node_count - 1:
            return 'linear'
        elif connection_count > node_count:
            return 'complex_branching'
        else:
            return 'simple_branching'
    
    def _extract_searchable_keywords(self, automation: Dict[str, Any]) -> List[str]:
        """Extract searchable keywords from automation"""
        keywords = []
        
        # From name and description
        name = automation.get('name', '')
        keywords.extend(re.findall(r'\w+', name.lower()))
        
        # From node types and names
        nodes = automation.get('nodes', [])
        for node in nodes:
            node_type = node.get('type', '')
            node_name = node.get('name', '')
            
            # Extract meaningful parts from node type
            type_parts = node_type.replace('n8n-nodes-base.', '').lower()
            keywords.append(type_parts)
            
            # Extract words from node name
            keywords.extend(re.findall(r'\w+', node_name.lower()))
        
        # Remove duplicates and common words
        keywords = list(set(keywords))
        common_words = {'node', 'base', 'n8n', 'the', 'and', 'or', 'in', 'on', 'at', 'to', 'for'}
        keywords = [k for k in keywords if k not in common_words and len(k) > 2]
        
        return keywords
    
    def _is_valid_table_name(self, table_name: str) -> bool:
        """Validate table name to prevent SQL injection"""
        import re
        # Allow only alphanumeric characters, underscores, and specific known table names
        if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', table_name):
            return False
        # Additional whitelist of allowed table names
        allowed_tables = ['n8n_automations', 'automations', 'workflows', 'test_automations']
        return table_name in allowed_tables
    
    def _generate_id(self, automation: Dict[str, Any]) -> str:
        """Generate consistent ID for automation (not for security purposes)"""
        content = json.dumps(automation, sort_keys=True)
        return hashlib.md5(content.encode(), usedforsecurity=False).hexdigest()[:16]
    
    def create_optimized_searchable_text(self, automation: Dict[str, Any], features: Dict[str, Any]) -> str:
        """Create optimized searchable text for embedding"""
        
        components = [
            f"Automation: {features['name']}",
            f"Trigger: {features['trigger_info']['type']}",
            f"Pattern: {features['flow_pattern']}",
            f"Complexity: {features['complexity_score']}"
        ]
        
        # Add action categories
        active_actions = [k for k, v in features['action_types'].items() if v > 0]
        if active_actions:
            components.append(f"Actions: {', '.join(active_actions)}")
        
        # Add key node types
        key_nodes = [t.replace('n8n-nodes-base.', '') for t in features['node_types'][:5]]
        if key_nodes:
            components.append(f"Nodes: {', '.join(key_nodes)}")
        
        # Add searchable keywords
        if features['searchable_keywords']:
            components.append(f"Keywords: {', '.join(features['searchable_keywords'][:10])}")
        
        return ' | '.join(components)
    
    def search_with_adaptive_strategy(self, 
                                    query: str, 
                                    model_size: str,
                                    additional_filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Search with adaptive strategy based on model and query"""
        
        strategy = self.analyze_request_for_search_strategy(query, model_size)
        config = self.search_configs[strategy]
        
        logger.info(f"Using search strategy: {strategy}")
        
        # Step 1: Semantic search
        semantic_results = self._semantic_search(query, config, additional_filters)
        
        # Step 2: Hybrid search if enabled
        if config.use_hybrid_search:
            keyword_results = self._keyword_search(query, config.max_examples)
            combined_results = self._combine_search_results(semantic_results, keyword_results)
        else:
            combined_results = semantic_results
        
        # Step 3: Rerank if enabled
        if config.rerank_results:
            combined_results = self._rerank_results(query, combined_results)
        
        # Step 4: Chunk examples if enabled
        if config.chunk_examples:
            combined_results = self._chunk_examples_for_context(combined_results, model_size)
        
        return combined_results[:config.max_examples]
    
    def _semantic_search(self, 
                        query: str, 
                        config: VectorSearchConfig,
                        additional_filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Perform semantic vector search"""
        
        try:
            # Create query embedding
            query_embedding = self.embedder.encode(query)
            query_normalized = query_embedding / np.linalg.norm(query_embedding)
            
            # Build SQL query with filters
            sql_base = f"""
                SELECT 
                    automation_id, name, full_json, searchable_text,
                    1 - (embedding <=> %s) AS similarity,
                    trigger_type, workflow_pattern, complexity_score
                FROM {self.table_name}
            """
            
            params = [query_normalized]
            where_clauses = [f"1 - (embedding <=> %s) >= %s"]
            params.append(query_normalized)
            params.append(config.similarity_threshold)
            
            # Add additional filters
            if additional_filters:
                for key, value in additional_filters.items():
                    if key == 'max_complexity':
                        where_clauses.append("complexity_score <= %s")
                        params.append(value)
                    elif key == 'trigger_type':
                        where_clauses.append("trigger_type = %s")
                        params.append(value)
                    elif key == 'workflow_pattern':
                        where_clauses.append("workflow_pattern = %s")
                        params.append(value)
            
            sql_query = sql_base + " WHERE " + " AND ".join(where_clauses)
            sql_query += " ORDER BY embedding <=> %s LIMIT %s"
            params.extend([query_normalized, config.max_examples * 2])  # Get extra for filtering
            
            with self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                cur.execute(sql_query, params)
                results = cur.fetchall()
            
            # Format results
            formatted_results = []
            for row in results:
                formatted_results.append({
                    'automation_id': row['automation_id'],
                    'name': row['name'],
                    'similarity': float(row['similarity']),
                    'automation': json.loads(row['full_json']),
                    'metadata': {
                        'trigger_type': row['trigger_type'],
                        'workflow_pattern': row['workflow_pattern'],
                        'complexity_score': row['complexity_score']
                    },
                    'search_type': 'semantic'
                })
            
            logger.info(f"Semantic search found {len(formatted_results)} results")
            return formatted_results
            
        except Exception as e:
            logger.error(f"Semantic search error: {e}")
            return []
    
    def _keyword_search(self, query: str, max_results: int) -> List[Dict[str, Any]]:
        """Perform keyword-based search"""
        
        try:
            # Extract keywords from query
            query_keywords = re.findall(r'\w+', query.lower())
            query_keywords = [k for k in query_keywords if len(k) > 2]
            
            if not query_keywords:
                return []
            
            # Build keyword search query
            keyword_conditions = []
            params = []
            
            for keyword in query_keywords[:5]:  # Limit to top 5 keywords
                keyword_conditions.append("(searchable_text ILIKE %s OR name ILIKE %s)")
                params.extend([f'%{keyword}%', f'%{keyword}%'])
            
            sql_query = f"""
                SELECT 
                    automation_id, name, full_json, searchable_text,
                    trigger_type, workflow_pattern, complexity_score
                FROM {self.table_name}
                WHERE {' OR '.join(keyword_conditions)}
                ORDER BY 
                    CASE 
                        WHEN name ILIKE %s THEN 1
                        WHEN searchable_text ILIKE %s THEN 2
                        ELSE 3
                    END
                LIMIT %s
            """
            
            # Add relevance scoring parameters
            main_keyword = query_keywords[0] if query_keywords else query
            params.extend([f'%{main_keyword}%', f'%{main_keyword}%', max_results])
            
            with self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                cur.execute(sql_query, params)
                results = cur.fetchall()
            
            # Format results
            formatted_results = []
            for row in results:
                formatted_results.append({
                    'automation_id': row['automation_id'],
                    'name': row['name'],
                    'similarity': 0.8,  # Default similarity for keyword matches
                    'automation': json.loads(row['full_json']),
                    'metadata': {
                        'trigger_type': row['trigger_type'],
                        'workflow_pattern': row['workflow_pattern'],
                        'complexity_score': row['complexity_score']
                    },
                    'search_type': 'keyword'
                })
            
            logger.info(f"Keyword search found {len(formatted_results)} results")
            return formatted_results
            
        except Exception as e:
            logger.error(f"Keyword search error: {e}")
            return []
    
    def _combine_search_results(self, 
                               semantic_results: List[Dict[str, Any]], 
                               keyword_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Combine and deduplicate search results"""
        
        # Create a map to track seen automations
        seen_ids = set()
        combined = []
        
        # Add semantic results first (higher priority)
        for result in semantic_results:
            if result['automation_id'] not in seen_ids:
                seen_ids.add(result['automation_id'])
                combined.append(result)
        
        # Add keyword results that weren't already found
        for result in keyword_results:
            if result['automation_id'] not in seen_ids:
                seen_ids.add(result['automation_id'])
                # Boost similarity for keyword matches if they have good semantic score too
                result['similarity'] = min(0.9, result['similarity'] + 0.1)
                combined.append(result)
        
        # Sort by similarity
        combined.sort(key=lambda x: x['similarity'], reverse=True)
        return combined
    
    def _rerank_results(self, query: str, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Rerank results based on additional relevance factors"""
        
        query_lower = query.lower()
        
        for result in results:
            automation = result['automation']
            metadata = result['metadata']
            
            # Calculate additional relevance factors
            relevance_boost = 0
            
            # Boost if automation name matches query terms
            name_words = result['name'].lower().split()
            query_words = query_lower.split()
            name_match_score = len(set(name_words) & set(query_words)) / len(query_words)
            relevance_boost += name_match_score * 0.1
            
            # Boost based on complexity match
            if 'simple' in query_lower and metadata['complexity_score'] < 10:
                relevance_boost += 0.05
            elif 'complex' in query_lower and metadata['complexity_score'] > 20:
                relevance_boost += 0.05
            
            # Boost based on specific node type matches
            nodes = automation.get('nodes', [])
            node_types = [n.get('type', '').lower() for n in nodes]
            
            if 'webhook' in query_lower and any('webhook' in t for t in node_types):
                relevance_boost += 0.08
            if 'email' in query_lower and any('email' in t for t in node_types):
                relevance_boost += 0.08
            if 'database' in query_lower and any(any(db in t for db in ['mysql', 'postgres', 'mongo']) for t in node_types):
                relevance_boost += 0.08
            
            # Apply the boost
            result['similarity'] = min(1.0, result['similarity'] + relevance_boost)
            result['relevance_boost'] = relevance_boost
        
        # Re-sort by updated similarity
        results.sort(key=lambda x: x['similarity'], reverse=True)
        return results
    
    def _chunk_examples_for_context(self, results: List[Dict[str, Any]], model_size: str) -> List[Dict[str, Any]]:
        """Chunk examples to fit model context window better"""
        
        if model_size != 'small':
            return results  # Only chunk for small models
        
        for result in results:
            automation = result['automation']
            
            # Create simplified version for small models
            nodes = automation.get('nodes', [])
            
            # Keep only essential node information
            simplified_nodes = []
            for node in nodes[:5]:  # Limit to 5 nodes max
                simplified_node = {
                    'type': node.get('type', ''),
                    'name': node.get('name', ''),
                    'id': node.get('id', '')
                }
                # Only include parameters if they're simple
                params = node.get('parameters', {})
                if params and len(str(params)) < 200:
                    simplified_node['parameters'] = params
                
                simplified_nodes.append(simplified_node)
            
            # Simplify connections
            connections = automation.get('connections', {})
            simplified_connections = {}
            
            for source, targets in list(connections.items())[:3]:  # Max 3 connections
                simplified_connections[source] = targets
            
            # Create chunked version
            result['chunked_automation'] = {
                'id': automation.get('id'),
                'name': automation.get('name'),
                'nodes': simplified_nodes,
                'connections': simplified_connections
            }
        
        return results

# Example usage
if __name__ == "__main__":
    # Test the enhanced optimizer
    db_conn = "postgresql://pguser:pgpassword@pgsql-db:5432/database"
    
    try:
        optimizer = EnhancedVectorOptimizer(db_conn)
        
        # Test search strategies
        test_queries = [
            ("Create a simple webhook", "small"),
            ("Complex automation with database and email", "medium"),
            ("Advanced workflow with multiple conditions", "large")
        ]
        
        for query, model_size in test_queries:
            print(f"\nTesting: {query} with {model_size} model")
            strategy = optimizer.analyze_request_for_search_strategy(query, model_size)
            print(f"Selected strategy: {strategy}")
            
            # Would perform actual search here
            # results = optimizer.search_with_adaptive_strategy(query, model_size)
            
    except Exception as e:
        print(f"Error: {e}")