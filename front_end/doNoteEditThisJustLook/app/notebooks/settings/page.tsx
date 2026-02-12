"use client"

import { Settings } from "lucide-react"

export default function NotebookSettingsPage() {
  return (
    <div className="h-full w-full overflow-y-auto p-6 bg-[#0a0a0a]">
      <div className="max-w-3xl mx-auto space-y-6">
        <div className="flex items-center gap-3">
          <Settings className="h-5 w-5 text-blue-400" />
          <div>
            <h1 className="text-2xl font-semibold text-white">Settings</h1>
            <p className="text-sm text-gray-400">
              Configure processing, embedding, files, and YouTube preferences.
            </p>
          </div>
        </div>

        <div className="space-y-4">
          <div className="border border-gray-800 rounded-lg p-4 bg-gray-900/40">
            <h2 className="text-sm font-semibold text-white mb-2">Processing</h2>
            <div className="flex items-center justify-between text-sm text-gray-400">
              <span>Auto-process new sources</span>
              <input type="checkbox" defaultChecked />
            </div>
          </div>

          <div className="border border-gray-800 rounded-lg p-4 bg-gray-900/40">
            <h2 className="text-sm font-semibold text-white mb-2">Embedding</h2>
            <div className="flex items-center justify-between text-sm text-gray-400">
              <span>Auto-embed new sources</span>
              <input type="checkbox" defaultChecked />
            </div>
          </div>

          <div className="border border-gray-800 rounded-lg p-4 bg-gray-900/40">
            <h2 className="text-sm font-semibold text-white mb-2">Files</h2>
            <div className="flex items-center justify-between text-sm text-gray-400">
              <span>Auto-delete uploads after processing</span>
              <input type="checkbox" />
            </div>
          </div>

          <div className="border border-gray-800 rounded-lg p-4 bg-gray-900/40">
            <h2 className="text-sm font-semibold text-white mb-2">YouTube</h2>
            <div className="flex items-center justify-between text-sm text-gray-400">
              <span>Preferred transcript language</span>
              <select className="bg-gray-800 border border-gray-700 text-white text-xs rounded px-2 py-1">
                <option>English</option>
                <option>Spanish</option>
                <option>French</option>
                <option>German</option>
              </select>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}








