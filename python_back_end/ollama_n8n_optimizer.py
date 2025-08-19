import json
import logging
import requests
import re
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass
import psutil
import gc
import time

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@dataclass
class ModelCapability:
    """Dynamic model capability assessment"""
    name: str
    size_category: str  # "small", "medium", "large"
    context_window: int
    optimal_temperature: float
    max_examples: int
    chunk_size: int
    supports_structured: bool

class OllamaN8NOptimizer:
    """Dynamic optimizer for n8n automation generation with Ollama models"""
    
    def __init__(self, ollama_url: str = "http://ollama:11434"):
        self.ollama_url = ollama_url
        self.model_cache = {}
        self.performance_history = {}
        
        # Size indicators for dynamic model classification
        self.size_indicators = {
            'small': ['7b', '3b', '1b', 'tiny', 'mini'],
            'medium': ['13b', '8b', '11b', '12b'],
            'large': ['70b', '34b', '30b', '65b', '175b', 'large', 'xl']
        }
        
    def get_available_models(self) -> List[str]:
        """Get list of available Ollama models"""
        try:
            response = requests.get(f"{self.ollama_url}/api/tags")
            if response.status_code == 200:
                models = response.json().get('models', [])
                return [model['name'] for model in models]
            else:
                logger.error(f"Failed to get models: {response.status_code}")
                return []
        except Exception as e:
            logger.error(f"Error getting models: {e}")
            return []
    
    def classify_model_size(self, model_name: str) -> str:
        """Dynamically classify model size based on name"""
        model_lower = model_name.lower()
        
        # Check for explicit size indicators
        for size, indicators in self.size_indicators.items():
            if any(indicator in model_lower for indicator in indicators):
                return size
        
        # Fallback classification based on common patterns
        if any(term in model_lower for term in ['mistral', 'llama2', 'codellama']):
            if '13b' in model_lower or '11b' in model_lower:
                return 'medium'
            elif '70b' in model_lower or '34b' in model_lower:
                return 'large'
            else:
                return 'small'  # Assume 7b or similar
        
        # Default to medium if unsure
        return 'medium'
    
    def assess_model_capabilities(self, model_name: str) -> ModelCapability:
        """Dynamically assess model capabilities"""
        if model_name in self.model_cache:
            return self.model_cache[model_name]
        
        size_category = self.classify_model_size(model_name)
        
        # Dynamic capability assignment
        capabilities = {
            'small': ModelCapability(
                name=model_name,
                size_category='small',
                context_window=2048,
                optimal_temperature=0.3,  # More deterministic for better JSON
                max_examples=2,
                chunk_size=1500,
                supports_structured=True
            ),
            'medium': ModelCapability(
                name=model_name,
                size_category='medium', 
                context_window=4096,
                optimal_temperature=0.4,
                max_examples=3,
                chunk_size=3000,
                supports_structured=True
            ),
            'large': ModelCapability(
                name=model_name,
                size_category='large',
                context_window=8192,
                optimal_temperature=0.5,
                max_examples=4,
                chunk_size=6000,
                supports_structured=False  # May need simpler prompts
            )
        }
        
        capability = capabilities[size_category]
        self.model_cache[model_name] = capability
        return capability
    
    def optimize_memory_for_model(self, model_size: str):
        """Optimize system memory based on expected model size"""
        gc.collect()
        
        # More aggressive cleanup for larger models
        if model_size == 'large':
            # Clear any unnecessary caches
            if hasattr(gc, 'set_threshold'):
                gc.set_threshold(100, 10, 10)  # More frequent GC
        
        memory_info = psutil.virtual_memory()
        logger.info(f"Memory optimization for {model_size} model - Available: {memory_info.available / (1024**3):.1f}GB")
    
    def create_dynamic_prompt(self, 
                            user_request: str, 
                            examples: List[Dict[str, Any]], 
                            model_name: str) -> str:
        """Create optimized prompt based on dynamic model assessment"""
        
        capability = self.assess_model_capabilities(model_name)
        limited_examples = examples[:capability.max_examples]
        
        # Choose prompt strategy based on model capabilities
        if capability.size_category == 'small':
            return self._create_small_model_prompt(user_request, limited_examples, model_name)
        elif capability.size_category == 'medium':
            return self._create_medium_model_prompt(user_request, limited_examples, model_name)
        else:
            return self._create_large_model_prompt(user_request, limited_examples, model_name)
    
    def _create_small_model_prompt(self, user_request: str, examples: List[Dict[str, Any]], model_name: str) -> str:
        """Highly structured prompt for small models (7B and below)"""
        
        # Extract minimal, focused patterns
        patterns = []
        for example in examples:
            automation = example.get('automation', {})
            nodes = automation.get('nodes', [])
            
            # Create ultra-minimal pattern
            pattern = {
                'trigger': nodes[0].get('type', '') if nodes else 'webhook',
                'actions': [n.get('type', '') for n in nodes[1:3]],  # Max 2 actions
                'node_count': len(nodes)
            }
            patterns.append(pattern)
        
        # Check if this looks like a coding-focused model
        is_code_model = any(term in model_name.lower() for term in ['code', 'coding', 'programmer'])
        
        if is_code_model:
            prompt = f"""// n8n workflow generator
// Input: {user_request}
// Generate valid JSON only

/* Examples: {json.dumps(patterns)} */

// Output format:
{{"id":"workflow","name":"Generated","nodes":[{{"id":"node1","name":"Start","type":"trigger","position":[0,0]}}],"connections":{{}}}}

// Generate n8n workflow JSON:
"""
        else:
            prompt = f"""Generate n8n automation JSON for: {user_request}

Examples: {json.dumps(patterns, indent=2)}

RULES:
- Return ONLY valid JSON
- Required: id, name, nodes, connections
- Each node needs: id, name, type, position
- Keep it simple and functional

JSON:"""
        
        return prompt
    
    def _create_medium_model_prompt(self, user_request: str, examples: List[Dict[str, Any]], model_name: str) -> str:
        """Balanced prompt for medium models (8B-13B)"""
        
        # Extract structured examples with more detail
        structured_examples = []
        for example in examples:
            automation = example.get('automation', {})
            metadata = example.get('metadata', {})
            
            structured = {
                'purpose': metadata.get('name', 'Automation'),
                'trigger_type': metadata.get('trigger_type', ''),
                'workflow_pattern': metadata.get('workflow_pattern', 'linear'),
                'node_types': [n.get('type', '') for n in automation.get('nodes', [])],
                'complexity': len(automation.get('nodes', []))
            }
            structured_examples.append(structured)
        
        prompt = f"""Create an n8n automation workflow for: {user_request}

Reference examples:
{json.dumps(structured_examples, indent=2)}

Generate a complete n8n workflow JSON with:
1. Unique workflow id and descriptive name
2. Array of nodes with proper structure (id, name, type, position)
3. Connections object defining the workflow flow
4. Appropriate node types for the requested functionality

Ensure the JSON is valid and follows n8n automation format exactly.

n8n workflow JSON:"""
        
        return prompt
    
    def _create_large_model_prompt(self, user_request: str, examples: List[Dict[str, Any]], model_name: str) -> str:
        """Comprehensive prompt for large models (30B+)"""
        
        # Full examples with explanations
        detailed_examples = []
        for i, example in enumerate(examples):
            automation = example.get('automation', {})
            metadata = example.get('metadata', {})
            
            detailed = {
                'workflow_name': automation.get('name', f'Example {i+1}'),
                'description': f"This workflow demonstrates {metadata.get('workflow_pattern', 'processing')} pattern",
                'structure': automation,
                'key_features': {
                    'trigger_type': metadata.get('trigger_type', ''),
                    'has_conditions': 'if' in str(automation).lower(),
                    'complexity_score': metadata.get('complexity_score', 0)
                }
            }
            detailed_examples.append(detailed)
        
        prompt = f"""You are an expert n8n automation developer. Create a comprehensive workflow for this request:

REQUEST: {user_request}

REFERENCE EXAMPLES:
{json.dumps(detailed_examples, indent=2)}

Please analyze the request and create a complete n8n workflow JSON that:
1. Properly addresses the user's needs
2. Follows n8n workflow structure conventions
3. Uses appropriate node types and configurations
4. Includes proper error handling where applicable
5. Maintains clean, logical flow connections

Generate the complete n8n automation workflow as valid JSON:"""
        
        return prompt
    
    def generate_with_ollama(self, 
                           prompt: str, 
                           model_name: str, 
                           max_retries: int = 3) -> Optional[str]:
        """Generate with Ollama API and automatic retry"""
        
        capability = self.assess_model_capabilities(model_name)
        
        # Optimize memory before generation
        self.optimize_memory_for_model(capability.size_category)
        
        generation_params = {
            "model": model_name,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": capability.optimal_temperature,
                "top_p": 0.9,
                "top_k": 40,
                "num_predict": 1000,  # Reasonable limit for JSON
                "stop": ["Human:", "User:", "<|endoftext|>", "</s>"]
            }
        }
        
        for attempt in range(max_retries):
            try:
                start_time = time.time()
                
                response = requests.post(
                    f"{self.ollama_url}/api/generate",
                    json=generation_params,
                    timeout=120
                )
                
                if response.status_code == 200:
                    result = response.json()
                    generated_text = result.get('response', '')
                    
                    # Track performance
                    generation_time = time.time() - start_time
                    self._update_performance_history(model_name, generation_time, True)
                    
                    logger.info(f"Generated with {model_name} in {generation_time:.2f}s")
                    return generated_text
                else:
                    logger.error(f"Ollama API error: {response.status_code} - {response.text}")
                    
            except requests.exceptions.Timeout:
                logger.error(f"Timeout on attempt {attempt + 1} with {model_name}")
                # Reduce context for next attempt
                if len(prompt) > 1000:
                    prompt = prompt[:len(prompt)//2] + "\n\nGenerate n8n JSON:"
                    
            except Exception as e:
                logger.error(f"Generation error on attempt {attempt + 1}: {e}")
                
                # Track failure
                self._update_performance_history(model_name, 0, False)
        
        return None
    
    def _update_performance_history(self, model_name: str, generation_time: float, success: bool):
        """Track model performance for future optimization"""
        if model_name not in self.performance_history:
            self.performance_history[model_name] = {
                'success_count': 0,
                'failure_count': 0,
                'avg_time': 0,
                'total_time': 0
            }
        
        history = self.performance_history[model_name]
        
        if success:
            history['success_count'] += 1
            history['total_time'] += generation_time
            history['avg_time'] = history['total_time'] / history['success_count']
        else:
            history['failure_count'] += 1
    
    def get_recommended_model(self, user_request: str, available_models: List[str]) -> Optional[str]:
        """Recommend best model based on request complexity and performance history"""
        
        if not available_models:
            return None
        
        # Analyze request complexity
        request_complexity = self._analyze_request_complexity(user_request)
        
        # Score models based on capability and performance
        model_scores = {}
        for model in available_models:
            capability = self.assess_model_capabilities(model)
            performance = self.performance_history.get(model, {'success_count': 1, 'failure_count': 0, 'avg_time': 5})
            
            # Calculate score
            success_rate = performance['success_count'] / (performance['success_count'] + performance['failure_count'])
            time_score = max(0, 10 - performance['avg_time'])  # Prefer faster models
            
            capability_match = self._match_capability_to_complexity(capability, request_complexity)
            
            total_score = (success_rate * 0.4) + (time_score * 0.3) + (capability_match * 0.3)
            model_scores[model] = total_score
        
        # Return highest scoring model
        best_model = max(model_scores.items(), key=lambda x: x[1])
        logger.info(f"Recommended model: {best_model[0]} (score: {best_model[1]:.2f})")
        
        return best_model[0]
    
    def _analyze_request_complexity(self, request: str) -> str:
        """Analyze complexity of user request"""
        complexity_indicators = {
            'simple': ['webhook', 'email', 'send', 'notify'],
            'medium': ['database', 'condition', 'if', 'process', 'transform'],
            'complex': ['multiple', 'loop', 'iterate', 'schedule', 'complex', 'advanced']
        }
        
        request_lower = request.lower()
        
        for complexity, indicators in complexity_indicators.items():
            if any(indicator in request_lower for indicator in indicators):
                return complexity
        
        # Word count based fallback
        if len(request.split()) > 15:
            return 'complex'
        elif len(request.split()) > 8:
            return 'medium'
        else:
            return 'simple'
    
    def _match_capability_to_complexity(self, capability: ModelCapability, complexity: str) -> float:
        """Match model capability to request complexity"""
        match_scores = {
            ('small', 'simple'): 1.0,
            ('small', 'medium'): 0.6,
            ('small', 'complex'): 0.3,
            ('medium', 'simple'): 0.8,
            ('medium', 'medium'): 1.0,
            ('medium', 'complex'): 0.7,
            ('large', 'simple'): 0.6,
            ('large', 'medium'): 0.8,
            ('large', 'complex'): 1.0
        }
        
        return match_scores.get((capability.size_category, complexity), 0.5)
    
    def extract_and_validate_json(self, response: str) -> Tuple[bool, Optional[Dict[str, Any]], List[str]]:
        """Extract, validate and fix JSON from model response"""
        errors = []
        
        # Extract JSON
        extracted_json = self._extract_json_from_response(response)
        if not extracted_json:
            return False, None, ["No valid JSON found in response"]
        
        # Basic validation
        required_fields = ['nodes', 'connections']
        for field in required_fields:
            if field not in extracted_json:
                extracted_json[field] = [] if field == 'nodes' else {}
                errors.append(f"Missing {field} - added default")
        
        # Fix common issues
        fixed_json = self._fix_n8n_structure(extracted_json)
        
        # Validate nodes
        nodes = fixed_json.get('nodes', [])
        for i, node in enumerate(nodes):
            if not isinstance(node, dict):
                continue
                
            if 'id' not in node:
                node['id'] = f"node_{i}"
                errors.append(f"Added missing ID to node {i}")
            
            if 'position' not in node:
                node['position'] = [i * 200, 100]
                errors.append(f"Added position to node {i}")
        
        is_valid = len([e for e in errors if 'Missing' in e]) == 0
        return is_valid, fixed_json, errors
    
    def _extract_json_from_response(self, response: str) -> Optional[Dict[str, Any]]:
        """Extract JSON from various response formats"""
        try:
            # Try direct JSON parse
            return json.loads(response.strip())
        except:
            pass
        
        # Try to find JSON in response
        patterns = [
            r'```json\s*(.*?)\s*```',
            r'```\s*(.*?)\s*```',
            r'\{.*\}',
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, response, re.DOTALL)
            for match in matches:
                try:
                    return json.loads(match.strip())
                except:
                    continue
        
        return None
    
    def _fix_n8n_structure(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Fix common n8n structure issues"""
        fixed = data.copy()
        
        # Ensure basic structure
        if 'id' not in fixed:
            fixed['id'] = 'generated_workflow'
        
        if 'name' not in fixed:
            fixed['name'] = 'Generated Automation'
        
        # Ensure connections is a dict
        if not isinstance(fixed.get('connections'), dict):
            fixed['connections'] = {}
        
        return fixed

# Example usage
if __name__ == "__main__":
    optimizer = OllamaN8NOptimizer()
    
    # Test model detection
    available_models = ["mistral:7b", "llama2:13b", "codellama:7b"]
    print("Available models:", available_models)
    
    for model in available_models:
        capability = optimizer.assess_model_capabilities(model)
        print(f"{model}: {capability.size_category} - max_examples: {capability.max_examples}")
    
    # Test recommendation
    request = "Create a complex webhook that processes data and sends multiple notifications"
    recommended = optimizer.get_recommended_model(request, available_models)
    print(f"Recommended for '{request}': {recommended}")