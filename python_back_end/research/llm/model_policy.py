"""
Model selection policies for research tasks.

Automatically chooses appropriate models based on task complexity,
processing stage, and performance requirements.
"""

import logging
from typing import Dict, Optional, List, Any
from dataclasses import dataclass
from enum import Enum

from .ollama_client import ModelTier

logger = logging.getLogger(__name__)


class TaskType(Enum):
    """Types of research tasks with different model requirements"""
    SEARCH_PLANNING = "search_planning"      # Query planning and decomposition
    CONTENT_EXTRACTION = "content_extraction" # HTML/PDF text extraction  
    CHUNK_PROCESSING = "chunk_processing"    # MAP phase individual chunks
    SYNTHESIS = "synthesis"                  # REDUCE phase synthesis
    VERIFICATION = "verification"            # Quote and fact verification
    RERANKING = "reranking"                 # Semantic reranking
    FACT_CHECKING = "fact_checking"         # Specialized fact checking
    COMPARISON = "comparison"               # Comparative analysis


@dataclass
class ModelConfig:
    """Configuration for a model including capabilities and limits"""
    name: str
    tier: ModelTier
    max_context: int           # Maximum context length
    cost_factor: float         # Relative cost (1.0 = baseline)
    speed_factor: float        # Relative speed (1.0 = baseline)
    reasoning_score: float     # Reasoning capability (0-1)
    accuracy_score: float      # Factual accuracy (0-1)
    creativity_score: float    # Creative writing (0-1)
    available: bool = True
    
    def suitability_score(self, task_requirements: Dict[str, float]) -> float:
        """Calculate suitability score for task requirements"""
        score = 0.0
        weights = {
            "reasoning": self.reasoning_score,
            "accuracy": self.accuracy_score, 
            "creativity": self.creativity_score,
            "speed": self.speed_factor,
            "cost": 1.0 / self.cost_factor  # Lower cost is better
        }
        
        for requirement, importance in task_requirements.items():
            if requirement in weights:
                score += weights[requirement] * importance
        
        return score


class ModelPolicy:
    """
    Smart model selection policy for research tasks.
    
    Automatically selects the most appropriate model based on:
    - Task complexity and requirements
    - Available resources and budget
    - Performance vs cost tradeoffs
    - Fallback strategies
    """
    
    def __init__(self, enable_cost_optimization: bool = True):
        self.enable_cost_optimization = enable_cost_optimization
        
        # Define available models and their capabilities
        self.models = self._initialize_model_configs()
        
        # Task requirements (importance 0-1 for each factor)
        self.task_requirements = self._initialize_task_requirements()
        
        # Usage tracking
        self._usage_stats = {}
    
    def _initialize_model_configs(self) -> Dict[str, ModelConfig]:
        """Initialize model configurations with capabilities"""
        return {
            # Small/Fast models
            "llama3.2:3b": ModelConfig(
                name="llama3.2:3b",
                tier=ModelTier.SMALL,
                max_context=8192,
                cost_factor=0.3,
                speed_factor=2.0,
                reasoning_score=0.6,
                accuracy_score=0.7,
                creativity_score=0.5
            ),
            "qwen2.5:3b": ModelConfig(
                name="qwen2.5:3b", 
                tier=ModelTier.SMALL,
                max_context=8192,
                cost_factor=0.3,
                speed_factor=1.8,
                reasoning_score=0.7,
                accuracy_score=0.8,
                creativity_score=0.5
            ),
            
            # Medium models  
            "mistral": ModelConfig(
                name="mistral",
                tier=ModelTier.MEDIUM,
                max_context=8192,
                cost_factor=1.0,
                speed_factor=1.0,
                reasoning_score=0.8,
                accuracy_score=0.8,
                creativity_score=0.7
            ),
            "llama3.2:7b": ModelConfig(
                name="llama3.2:7b",
                tier=ModelTier.MEDIUM, 
                max_context=8192,
                cost_factor=1.2,
                speed_factor=0.7,
                reasoning_score=0.8,
                accuracy_score=0.85,
                creativity_score=0.8
            ),
            "qwen2.5:7b": ModelConfig(
                name="qwen2.5:7b",
                tier=ModelTier.MEDIUM,
                max_context=32768,
                cost_factor=1.2,
                speed_factor=0.8,
                reasoning_score=0.85,
                accuracy_score=0.9,
                creativity_score=0.75
            ),
            
            # Large models
            "llama3.1:70b": ModelConfig(
                name="llama3.1:70b",
                tier=ModelTier.LARGE,
                max_context=8192,
                cost_factor=5.0,
                speed_factor=0.2,
                reasoning_score=0.95,
                accuracy_score=0.95,
                creativity_score=0.9,
                available=False  # May not always be available
            ),
            "qwen2.5:32b": ModelConfig(
                name="qwen2.5:32b",
                tier=ModelTier.LARGE, 
                max_context=32768,
                cost_factor=3.0,
                speed_factor=0.3,
                reasoning_score=0.9,
                accuracy_score=0.92,
                creativity_score=0.85,
                available=False  # May not always be available
            )
        }
    
    def _initialize_task_requirements(self) -> Dict[TaskType, Dict[str, float]]:
        """Define requirements for each task type"""
        return {
            TaskType.SEARCH_PLANNING: {
                "reasoning": 0.7,
                "accuracy": 0.6,
                "creativity": 0.8,
                "speed": 0.9,
                "cost": 0.8
            },
            TaskType.CONTENT_EXTRACTION: {
                "reasoning": 0.3,
                "accuracy": 0.9,
                "creativity": 0.2,
                "speed": 0.9,
                "cost": 0.9
            },
            TaskType.CHUNK_PROCESSING: {
                "reasoning": 0.6,
                "accuracy": 0.8,
                "creativity": 0.4,
                "speed": 0.8,
                "cost": 0.7
            },
            TaskType.SYNTHESIS: {
                "reasoning": 0.9,
                "accuracy": 0.8,
                "creativity": 0.7,
                "speed": 0.5,
                "cost": 0.4
            },
            TaskType.VERIFICATION: {
                "reasoning": 0.9,
                "accuracy": 0.95,
                "creativity": 0.2,
                "speed": 0.6,
                "cost": 0.5
            },
            TaskType.RERANKING: {
                "reasoning": 0.7,
                "accuracy": 0.8,
                "creativity": 0.3,
                "speed": 0.7,
                "cost": 0.8
            },
            TaskType.FACT_CHECKING: {
                "reasoning": 0.95,
                "accuracy": 0.98,
                "creativity": 0.1,
                "speed": 0.4,
                "cost": 0.3
            },
            TaskType.COMPARISON: {
                "reasoning": 0.9,
                "accuracy": 0.85,
                "creativity": 0.6,
                "speed": 0.5,
                "cost": 0.4
            }
        }
    
    def get_model_for_task(
        self,
        task_type: TaskType,
        context_length: Optional[int] = None,
        priority: str = "balanced",  # "speed", "accuracy", "cost", "balanced"
        fallback: bool = True
    ) -> str:
        """
        Select the best model for a specific task.
        
        Args:
            task_type: Type of task to perform
            context_length: Required context length (optional)
            priority: Optimization priority
            fallback: Whether to include fallback options
            
        Returns:
            Model name to use
        """
        requirements = self.task_requirements.get(task_type, {})
        
        # Adjust requirements based on priority
        if priority == "speed":
            requirements = {**requirements, "speed": 1.0, "cost": 0.9}
        elif priority == "accuracy":
            requirements = {**requirements, "accuracy": 1.0, "reasoning": 0.9}
        elif priority == "cost":
            requirements = {**requirements, "cost": 1.0, "speed": 0.8}
        
        # Filter available models
        available_models = {
            name: config for name, config in self.models.items()
            if config.available
        }
        
        # Filter by context length if specified
        if context_length:
            available_models = {
                name: config for name, config in available_models.items()
                if config.max_context >= context_length
            }
        
        if not available_models:
            logger.warning("No models available for requirements, using fallback")
            return "mistral"  # Safe fallback
        
        # Score models for this task
        model_scores = []
        for name, config in available_models.items():
            score = config.suitability_score(requirements)
            model_scores.append((score, name, config))
        
        # Sort by score (descending)
        model_scores.sort(reverse=True)
        
        # Log selection reasoning
        best_score, best_model, best_config = model_scores[0]
        logger.debug(f"Selected {best_model} for {task_type.value} (score: {best_score:.2f})")
        
        # Track usage
        self._track_usage(task_type, best_model)
        
        return best_model
    
    def get_fallback_models(self, primary_model: str, task_type: TaskType) -> List[str]:
        """Get ordered list of fallback models for a primary model"""
        primary_config = self.models.get(primary_model)
        if not primary_config:
            return ["mistral", "llama3.2:3b"]
        
        requirements = self.task_requirements.get(task_type, {})
        
        # Find models in same or lower tier
        candidate_models = []
        for name, config in self.models.items():
            if (name != primary_model and 
                config.available and
                config.tier.value <= primary_config.tier.value):
                
                score = config.suitability_score(requirements)
                candidate_models.append((score, name))
        
        # Sort by score and return names
        candidate_models.sort(reverse=True)
        return [name for score, name in candidate_models[:3]]
    
    def get_model_tier_for_complexity(self, complexity: str) -> ModelTier:
        """Map complexity level to model tier"""
        complexity_mapping = {
            "low": ModelTier.SMALL,
            "medium": ModelTier.MEDIUM, 
            "high": ModelTier.LARGE,
            "simple": ModelTier.SMALL,
            "complex": ModelTier.LARGE,
            "basic": ModelTier.SMALL,
            "advanced": ModelTier.LARGE
        }
        
        return complexity_mapping.get(complexity.lower(), ModelTier.MEDIUM)
    
    def estimate_cost(self, task_type: TaskType, num_requests: int = 1) -> float:
        """Estimate relative cost for task (1.0 = baseline)"""
        model = self.get_model_for_task(task_type)
        config = self.models.get(model)
        
        if not config:
            return 1.0
        
        return config.cost_factor * num_requests
    
    def _track_usage(self, task_type: TaskType, model: str):
        """Track model usage for analytics"""
        key = (task_type.value, model)
        self._usage_stats[key] = self._usage_stats.get(key, 0) + 1
    
    def get_usage_stats(self) -> Dict[str, Any]:
        """Get model usage statistics"""
        stats = {
            "total_requests": sum(self._usage_stats.values()),
            "by_task": {},
            "by_model": {},
            "by_task_model": dict(self._usage_stats)
        }
        
        # Aggregate by task
        for (task, model), count in self._usage_stats.items():
            stats["by_task"][task] = stats["by_task"].get(task, 0) + count
            stats["by_model"][model] = stats["by_model"].get(model, 0) + count
        
        return stats
    
    def update_model_availability(self, model_status: Dict[str, bool]):
        """Update model availability based on runtime status"""
        for model_name, available in model_status.items():
            if model_name in self.models:
                self.models[model_name].available = available
                logger.info(f"Updated {model_name} availability: {available}")


# Global policy instance
_global_policy = ModelPolicy()


def get_model_for_task(
    task_type: TaskType,
    context_length: Optional[int] = None,
    priority: str = "balanced",
    policy: Optional[ModelPolicy] = None
) -> str:
    """Convenience function to get model for task using global policy"""
    policy = policy or _global_policy
    return policy.get_model_for_task(task_type, context_length, priority)


def get_research_models() -> Dict[str, str]:
    """Get recommended models for each research stage"""
    return {
        "planning": get_model_for_task(TaskType.SEARCH_PLANNING, priority="speed"),
        "extraction": get_model_for_task(TaskType.CONTENT_EXTRACTION, priority="speed"),
        "processing": get_model_for_task(TaskType.CHUNK_PROCESSING, priority="balanced"),
        "synthesis": get_model_for_task(TaskType.SYNTHESIS, priority="accuracy"),
        "verification": get_model_for_task(TaskType.VERIFICATION, priority="accuracy"),
        "fact_check": get_model_for_task(TaskType.FACT_CHECKING, priority="accuracy")
    }


def set_cost_optimization(enabled: bool):
    """Enable or disable cost optimization globally"""
    _global_policy.enable_cost_optimization = enabled


def update_global_model_availability(model_status: Dict[str, bool]):
    """Update global model availability"""
    _global_policy.update_model_availability(model_status)