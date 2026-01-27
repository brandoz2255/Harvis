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
  selectedModel?: string,
  hasReasoning?: boolean
) => {
  const thoughtProcess = generateThoughtProcess(userPrompt, selectedModel)

  // Content-based detection: if hasReasoning is explicitly provided, use it
  // Otherwise fall back to name-based detection
  const type: 'thought' | 'reasoning' =
    hasReasoning !== undefined
      ? (hasReasoning ? 'reasoning' : 'thought')
      : (isReasoningModel(selectedModel) ? 'reasoning' : 'thought')

  const insightId = logThoughtProcess(
    thoughtProcess,
    selectedModel || 'Unknown Model',
    type
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

function isReasoningModel(name?: string): boolean {
  if (!name) return false
  const s = name.toLowerCase()

  return [
    /\breason(ing|er)?\b/,   // reasoning, reasoner
    /\bo[13]\b/,             // o1, o3 (OpenAI style)
    /\br1\b/,                // DeepSeek R1
    /\bthink(ing)?\b/,       // "thinking" SKUs
    /\bdeepseek\b/,          // DeepSeek family
    /\bqwen.*thinking\b/,    // Qwen Thinking
    /\bgpt-?5.*thinking\b/   // GPT-5 Thinking style names
  ].some(rx => rx.test(s))
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

  const modelType = (model || '').toLowerCase()
  
 if (isComplex) {
    if (isReasoningModel(model)) {
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
