import { useCallback } from 'react'
import { useInsightsStore } from '@/stores/insightsStore'

export const useAIInsights = () => {
  const { addInsight, updateInsight } = useInsightsStore()

  const logThoughtProcess = useCallback((
    content: string,
    model?: string,
    type: 'thought' | 'reasoning' | 'analysis' = 'thought'
  ) => {
    const title = getInsightTitle(type, model)
    
    const insightId = addInsight({
      type,
      status: 'thinking',
      title,
      content,
      model
    })
    
    return insightId
  }, [addInsight])

  const completeInsight = useCallback((
    insightId: string,
    result: string,
    status: 'done' | 'error' = 'done'
  ) => {
    updateInsight(insightId, {
      status,
      result
    })
  }, [updateInsight])

  const logUserInteraction = useCallback((
    userPrompt: string,
    selectedModel?: string
  ) => {
    // Generate thought process based on user input
    const thoughtProcess = generateThoughtProcess(userPrompt, selectedModel)
    
    const insightId = logThoughtProcess(
      thoughtProcess,
      selectedModel || 'Qwen2.VL',
      'thought'
    )
    
    return insightId
  }, [logThoughtProcess])

  const logReasoningProcess = useCallback((
    reasoning: string,
    model: string = 'Reasoning Model'
  ) => {
    const insightId = logThoughtProcess(
      reasoning,
      model,
      'reasoning'
    )
    
    return insightId
  }, [logThoughtProcess])

  return {
    logThoughtProcess,
    completeInsight,
    logUserInteraction,
    logReasoningProcess
  }
}

function getInsightTitle(type: string, model?: string): string {
  const modelName = model || 'AI'
  
  switch (type) {
    case 'thought':
      return `${modelName} Processing`
    case 'reasoning':
      return `${modelName} Reasoning`
    case 'analysis':
      return `${modelName} Analysis`
    default:
      return `${modelName} Insight`
  }
}

function generateThoughtProcess(userPrompt: string, model?: string): string {
  const promptLength = userPrompt.length
  const isComplex = promptLength > 100 || userPrompt.includes('?') || 
                   userPrompt.toLowerCase().includes('how') ||
                   userPrompt.toLowerCase().includes('why') ||
                   userPrompt.toLowerCase().includes('explain')

  const modelType = model?.toLowerCase() || 'qwen2.vl'
  
  if (isComplex) {
    if (modelType.includes('reasoning') || modelType.includes('o1')) {
      return `Analyzing complex query: "${userPrompt.substring(0, 50)}${promptLength > 50 ? '...' : ''}". Breaking down into components, considering context, and planning multi-step reasoning approach. Evaluating best response strategy.`
    } else if (modelType.includes('qwen') || modelType.includes('vision')) {
      return `Processing user request: "${userPrompt.substring(0, 50)}${promptLength > 50 ? '...' : ''}". Analyzing intent, checking for visual context, and determining optimal response path using multimodal capabilities.`
    } else {
      return `Interpreting user query: "${userPrompt.substring(0, 50)}${promptLength > 50 ? '...' : ''}". Assessing complexity, context requirements, and selecting appropriate knowledge domains for comprehensive response.`
    }
  } else {
    return `Quick processing: "${userPrompt.substring(0, 60)}${promptLength > 60 ? '...' : ''}". Direct response pattern identified, retrieving relevant information.`
  }
}