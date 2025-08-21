import json
import logging
from typing import Dict, Any, List, Optional, Tuple
from ollama_n8n_optimizer import OllamaN8NOptimizer
from enhanced_vector_optimizer import EnhancedVectorOptimizer
import time

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class N8NAutomationSystem:
    """Complete n8n automation generation system with dynamic optimization"""
    
    def __init__(self, 
                 ollama_url: str = "http://ollama:11434",
                 db_conn_string: str = "postgresql://pguser:pgpassword@pgsql-db:5432/database"):
        
        self.ollama_optimizer = OllamaN8NOptimizer(ollama_url)
        self.vector_optimizer = EnhancedVectorOptimizer(db_conn_string)
        
        # Performance tracking
        self.generation_history = {
            'total_requests': 0,
            'successful_generations': 0,
            'model_performance': {}
        }
        
        logger.info("N8N Automation System initialized")
    
    def add_automation_to_vector_db(self, automation: Dict[str, Any]) -> bool:
        """Add automation to vector database with enhanced features"""
        try:
            # Extract enhanced features
            features = self.vector_optimizer.extract_automation_features_enhanced(automation)
            
            # Create searchable text
            searchable_text = self.vector_optimizer.create_optimized_searchable_text(automation, features)
            
            # Create embedding
            embedding = self.vector_optimizer.embedder.encode(searchable_text)
            normalized_embedding = embedding / np.linalg.norm(embedding)
            
            # Insert into database
            with self.vector_optimizer.conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO n8n_automations (
                        automation_id, name, trigger_type, node_count, complexity_score,
                        categories, has_webhook, has_database, has_api_calls,
                        workflow_pattern, searchable_text, full_json, embedding
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (automation_id) DO UPDATE SET
                        name = EXCLUDED.name,
                        full_json = EXCLUDED.full_json,
                        embedding = EXCLUDED.embedding;
                    """,
                    (
                        features['automation_id'], features['name'], 
                        features['trigger_info']['type'], features['complexity_metrics']['node_count'],
                        features['complexity_score'], json.dumps(list(features['action_types'].keys())),
                        features['trigger_info']['has_webhook'], 
                        features['complexity_metrics']['database_nodes'] > 0,
                        features['complexity_metrics']['api_nodes'] > 0,
                        features['flow_pattern'], searchable_text, 
                        json.dumps(automation), normalized_embedding
                    )
                )
            self.vector_optimizer.conn.commit()
            
            logger.info(f"Added automation: {features['name']}")
            return True
            
        except Exception as e:
            logger.error(f"Error adding automation to vector DB: {e}")
            self.vector_optimizer.conn.rollback()
            return False
    
    def load_automation_dataset(self, file_path: str, batch_size: int = 100) -> Dict[str, Any]:
        """Load your 2500+ automations into the system"""
        
        results = {
            'total_loaded': 0,
            'successful': 0,
            'failed': 0,
            'errors': []
        }
        
        try:
            with open(file_path, 'r') as f:
                if file_path.endswith('.json'):
                    automations = json.load(f)
                else:
                    # Handle JSONL format
                    automations = []
                    for line in f:
                        if line.strip():
                            automations.append(json.loads(line.strip()))
            
            results['total_loaded'] = len(automations)
            logger.info(f"Loading {len(automations)} automations...")
            
            # Process in batches to manage memory
            for i in range(0, len(automations), batch_size):
                batch = automations[i:i + batch_size]
                
                for automation in batch:
                    if self.add_automation_to_vector_db(automation):
                        results['successful'] += 1
                    else:
                        results['failed'] += 1
                
                # Progress logging
                processed = min(i + batch_size, len(automations))
                logger.info(f"Processed {processed}/{len(automations)} automations")
            
            logger.info(f"Loading complete: {results['successful']}/{results['total_loaded']} successful")
            
        except Exception as e:
            logger.error(f"Error loading dataset: {e}")
            results['errors'].append(str(e))
        
        return results
    
    def generate_automation(self, 
                          user_request: str,
                          preferred_model: Optional[str] = None,
                          max_retries: int = 3) -> Dict[str, Any]:
        """Generate n8n automation with full optimization pipeline"""
        
        start_time = time.time()
        self.generation_history['total_requests'] += 1
        
        try:
            # Step 1: Get available models
            available_models = self.ollama_optimizer.get_available_models()
            if not available_models:
                return {
                    'success': False,
                    'error': 'No Ollama models available',
                    'generation_time': time.time() - start_time
                }
            
            # Step 2: Select optimal model
            if preferred_model and preferred_model in available_models:
                selected_model = preferred_model
            else:
                selected_model = self.ollama_optimizer.get_recommended_model(user_request, available_models)
            
            if not selected_model:
                selected_model = available_models[0]  # Fallback
            
            logger.info(f"Selected model: {selected_model}")
            
            # Step 3: Assess model capabilities
            model_capability = self.ollama_optimizer.assess_model_capabilities(selected_model)
            
            # Step 4: Search vector database with adaptive strategy
            search_results = self.vector_optimizer.search_with_adaptive_strategy(
                query=user_request,
                model_size=model_capability.size_category
            )
            
            logger.info(f"Found {len(search_results)} relevant examples")
            
            # Step 5: Create optimized prompt
            prompt = self.ollama_optimizer.create_dynamic_prompt(
                user_request=user_request,
                examples=search_results,
                model_name=selected_model
            )
            
            # Step 6: Generate with Ollama
            generated_response = self.ollama_optimizer.generate_with_ollama(
                prompt=prompt,
                model_name=selected_model,
                max_retries=max_retries
            )
            
            if not generated_response:
                return {
                    'success': False,
                    'error': 'Failed to generate response from model',
                    'model_used': selected_model,
                    'examples_found': len(search_results),
                    'generation_time': time.time() - start_time
                }
            
            # Step 7: Extract and validate JSON
            is_valid, extracted_json, validation_errors = self.ollama_optimizer.extract_and_validate_json(generated_response)
            
            # Track success
            if is_valid and extracted_json:
                self.generation_history['successful_generations'] += 1
                
                # Update model performance
                if selected_model not in self.generation_history['model_performance']:
                    self.generation_history['model_performance'][selected_model] = {
                        'attempts': 0,
                        'successes': 0,
                        'avg_time': 0
                    }
                
                perf = self.generation_history['model_performance'][selected_model]
                perf['attempts'] += 1
                perf['successes'] += 1
                generation_time = time.time() - start_time
                perf['avg_time'] = (perf['avg_time'] * (perf['attempts'] - 1) + generation_time) / perf['attempts']
            
            return {
                'success': is_valid,
                'automation': extracted_json if is_valid else None,
                'validation_errors': validation_errors,
                'raw_response': generated_response,
                'model_used': selected_model,
                'model_size_category': model_capability.size_category,
                'examples_found': len(search_results),
                'examples_used': search_results,
                'prompt_length': len(prompt),
                'generation_time': time.time() - start_time,
                'similarity_scores': [r.get('similarity', 0) for r in search_results]
            }
            
        except Exception as e:
            logger.error(f"Error generating automation: {e}")
            return {
                'success': False,
                'error': str(e),
                'generation_time': time.time() - start_time
            }
    
    def batch_generate_automations(self, requests: List[str]) -> Dict[str, Any]:
        """Generate multiple automations in batch"""
        
        results = {
            'total_requests': len(requests),
            'successful': 0,
            'failed': 0,
            'results': [],
            'performance_summary': {}
        }
        
        for i, request in enumerate(requests):
            logger.info(f"Processing request {i+1}/{len(requests)}: {request[:50]}...")
            
            result = self.generate_automation(request)
            results['results'].append({
                'request': request,
                'result': result
            })
            
            if result['success']:
                results['successful'] += 1
            else:
                results['failed'] += 1
            
            # Progress update
            if i % 10 == 0:
                success_rate = results['successful'] / max(1, i + 1) * 100
                logger.info(f"Progress: {i+1}/{len(requests)} - Success rate: {success_rate:.1f}%")
        
        # Performance summary
        results['performance_summary'] = {
            'success_rate': results['successful'] / results['total_requests'] * 100,
            'avg_generation_time': sum(r['result'].get('generation_time', 0) for r in results['results']) / len(results['results']),
            'model_usage': self._analyze_model_usage(results['results'])
        }
        
        return results
    
    def _analyze_model_usage(self, results: List[Dict[str, Any]]) -> Dict[str, int]:
        """Analyze which models were used in batch generation"""
        model_usage = {}
        
        for result_item in results:
            result = result_item['result']
            model = result.get('model_used')
            if model:
                model_usage[model] = model_usage.get(model, 0) + 1
        
        return model_usage
    
    def get_system_analytics(self) -> Dict[str, Any]:
        """Get comprehensive system analytics"""
        
        # Get available models
        available_models = self.ollama_optimizer.get_available_models()
        
        # Model capability analysis
        model_analysis = {}
        for model in available_models:
            capability = self.ollama_optimizer.assess_model_capabilities(model)
            model_analysis[model] = {
                'size_category': capability.size_category,
                'context_window': capability.context_window,
                'max_examples': capability.max_examples,
                'optimal_temperature': capability.optimal_temperature
            }
        
        return {
            'system_status': {
                'available_models': available_models,
                'model_analysis': model_analysis,
                'vector_db_connected': self.vector_optimizer.conn is not None
            },
            'generation_history': self.generation_history,
            'performance_insights': self._get_performance_insights()
        }
    
    def _get_performance_insights(self) -> Dict[str, Any]:
        """Generate performance insights"""
        insights = {}
        
        if self.generation_history['total_requests'] > 0:
            overall_success_rate = (self.generation_history['successful_generations'] / 
                                  self.generation_history['total_requests'] * 100)
            insights['overall_success_rate'] = overall_success_rate
            
            # Model performance insights
            best_model = None
            best_success_rate = 0
            
            for model, perf in self.generation_history['model_performance'].items():
                if perf['attempts'] > 0:
                    success_rate = perf['successes'] / perf['attempts'] * 100
                    if success_rate > best_success_rate:
                        best_success_rate = success_rate
                        best_model = model
            
            if best_model:
                insights['best_performing_model'] = {
                    'model': best_model,
                    'success_rate': best_success_rate
                }
        
        return insights
    
    def optimize_system_settings(self) -> Dict[str, Any]:
        """Auto-optimize system settings based on performance history"""
        
        optimizations = {
            'applied': [],
            'recommendations': []
        }
        
        # Analyze model performance
        for model, perf in self.generation_history['model_performance'].items():
            if perf['attempts'] > 5:  # Enough data
                success_rate = perf['successes'] / perf['attempts']
                
                if success_rate < 0.6:  # Low success rate
                    # Recommend adjusting settings for this model
                    capability = self.ollama_optimizer.assess_model_capabilities(model)
                    if capability.size_category == 'small':
                        optimizations['recommendations'].append(
                            f"Consider using more examples or higher similarity threshold for {model}"
                        )
                    
                if perf['avg_time'] > 30:  # Slow generation
                    optimizations['recommendations'].append(
                        f"Consider reducing context size or using smaller examples for {model}"
                    )
        
        return optimizations

# Example usage and testing
if __name__ == "__main__":
    # Initialize the system
    system = N8NAutomationSystem()
    
    # Test single generation
    user_request = "Create a webhook that receives user data and sends an email notification"
    
    print("Testing single automation generation...")
    result = system.generate_automation(user_request)
    
    print(f"Success: {result['success']}")
    print(f"Model used: {result.get('model_used')}")
    print(f"Examples found: {result.get('examples_found')}")
    print(f"Generation time: {result.get('generation_time', 0):.2f}s")
    
    if result['success']:
        automation = result['automation']
        print(f"Generated automation: {automation.get('name')}")
        print(f"Nodes: {len(automation.get('nodes', []))}")
    else:
        print(f"Error: {result.get('error')}")
    
    # Get system analytics
    print("\n" + "="*50)
    print("SYSTEM ANALYTICS")
    print("="*50)
    analytics = system.get_system_analytics()
    
    print(f"Available models: {analytics['system_status']['available_models']}")
    print(f"Total requests: {analytics['generation_history']['total_requests']}")
    print(f"Successful generations: {analytics['generation_history']['successful_generations']}")
    
    if analytics['performance_insights']:
        insights = analytics['performance_insights']
        if 'overall_success_rate' in insights:
            print(f"Overall success rate: {insights['overall_success_rate']:.1f}%")
        if 'best_performing_model' in insights:
            best = insights['best_performing_model']
            print(f"Best model: {best['model']} ({best['success_rate']:.1f}% success)")