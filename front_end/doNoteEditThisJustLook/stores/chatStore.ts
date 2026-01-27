import { create } from "zustand"

interface Message {
  role: "user" | "assistant"
  content: string
}

interface ChatStore {
  messages: Message[]
  addMessage: (msg: Message) => void
  clearMessages: () => void
}

export const useChatStore = create<ChatStore>((set) => ({
  messages: [],
  addMessage: (msg) =>
    set((state) => ({ messages: [...state.messages, msg] })),
  clearMessages: () => set({ messages: [] }),
}))