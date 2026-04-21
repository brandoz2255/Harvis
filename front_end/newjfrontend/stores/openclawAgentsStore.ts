/**
 * OpenClaw agents state store.
 *
 * Manages agent list, selected agent, files, tools catalog, and skills.
 */

import { create } from "zustand"
import type {
  AgentsListResult,
  GatewayAgentRow,
  AgentFileEntry,
  AgentsFilesListResult,
  ToolsCatalogResult,
  SkillStatusEntry,
  SkillStatusReport,
  AgentIdentityResult,
} from "@/lib/openclaw/types"

export type AgentsState = {
  agents: GatewayAgentRow[]
  selectedAgentId: string | null
  agentFiles: AgentFileEntry[]
  toolsCatalog: ToolsCatalogResult | null
  skills: SkillStatusEntry[]
  agentIdentity: AgentIdentityResult | null
  loading: boolean
  error: string | null

  // Actions
  setAgents: (result: AgentsListResult) => void
  setSelectedAgent: (id: string) => void
  setAgentFiles: (result: AgentsFilesListResult) => void
  setToolCatalog: (catalog: ToolsCatalogResult) => void
  setSkills: (report: SkillStatusReport) => void
  setAgentIdentity: (identity: AgentIdentityResult) => void
  setLoading: (loading: boolean) => void
  setError: (error: string | null) => void
  updateAgentFile: (agentId: string, file: AgentFileEntry) => void
  clearAgentData: () => void
}

export const useAgentsStore = create<AgentsState>((set, get) => ({
  agents: [],
  selectedAgentId: null,
  agentFiles: [],
  toolsCatalog: null,
  skills: [],
  agentIdentity: null,
  loading: false,
  error: null,

  setAgents: (result: AgentsListResult) => {
    set({
      agents: result.agents,
      selectedAgentId: result.defaultId || result.agents[0]?.id || null,
      error: null,
    })
  },

  setSelectedAgent: (id) => {
    set({ selectedAgentId: id })
  },

  setAgentFiles: (result: AgentsFilesListResult) => {
    set({ agentFiles: result.files, error: null })
  },

  setToolCatalog: (catalog: ToolsCatalogResult) => {
    set({ toolsCatalog: catalog, error: null })
  },

  setSkills: (report: SkillStatusReport) => {
    set({ skills: report.skills, error: null })
  },

  setAgentIdentity: (identity: AgentIdentityResult) => {
    set({ agentIdentity: identity })
  },

  setLoading: (loading) => set({ loading }),

  setError: (error) => set({ error }),

  updateAgentFile: (agentId, file) =>
    set((state) => ({
      agentFiles: state.agentFiles.map((f) => (f.name === file.name ? file : f)),
    })),

  clearAgentData: () =>
    set({
      agentFiles: [],
      toolsCatalog: null,
      skills: [],
      agentIdentity: null,
    }),
}))
