import { create } from 'zustand'

export interface InsightEntry {
  id: string
  type: 'thought' | 'reasoning' | 'analysis' | 'error'
  status: 'thinking' | 'done' | 'error'
  title: string
  content: string
  result?: string
  timestamp: Date
  model?: string
}

interface InsightsState {
  insights: InsightEntry[]
  addInsight: (insight: Omit<InsightEntry, 'id' | 'timestamp'>) => string
  updateInsight: (id: string, updates: Partial<InsightEntry>) => void
  clearInsights: () => void
}

export const useInsightsStore = create<InsightsState>((set, get) => ({
  insights: [],
  
  addInsight: (insight) => {
    const id = Date.now().toString() + Math.random().toString(36).substr(2, 9)
    const newInsight: InsightEntry = {
      ...insight,
      id,
      timestamp: new Date(),
    }
    
    console.log(`💡 [INSIGHTS_STORE] Adding insight:`, {
      id,
      type: newInsight.type,
      status: newInsight.status,
      title: newInsight.title,
      contentLength: newInsight.content.length
    })
    
    set(state => ({
      insights: [newInsight, ...state.insights.slice(0, 19)] // Keep last 20 insights
    }))
    
    return id
  },
  
  updateInsight: (id, updates) => {
    console.log(`🔄 [INSIGHTS_STORE] Updating insight:`, {
      id,
      updates
    })
    
    set(state => ({
      insights: state.insights.map(insight =>
        insight.id === id ? { ...insight, ...updates } : insight
      )
    }))
  },
  
  clearInsights: () => {
    set({ insights: [] })
  },
}))