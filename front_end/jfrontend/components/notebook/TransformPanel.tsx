'use client'

import { useState } from 'react'
import {
  Sparkles,
  FileText,
  List,
  HelpCircle,
  MapPin,
  Lightbulb,
  MessageSquare,
  ClipboardList,
  Loader2,
  Copy,
  CheckCircle,
  X
} from 'lucide-react'

interface TransformationType {
  id: string
  name: string
  description: string
  icon: React.ReactNode
}

const TRANSFORMATION_TYPES: TransformationType[] = [
  {
    id: 'summarize',
    name: 'Summarize',
    description: 'Create a concise summary of the content',
    icon: <FileText className="w-4 h-4" />
  },
  {
    id: 'key_points',
    name: 'Key Points',
    description: 'Extract the main takeaways',
    icon: <List className="w-4 h-4" />
  },
  {
    id: 'questions',
    name: 'Study Questions',
    description: 'Generate questions for studying',
    icon: <HelpCircle className="w-4 h-4" />
  },
  {
    id: 'outline',
    name: 'Outline',
    description: 'Create a structured outline',
    icon: <MapPin className="w-4 h-4" />
  },
  {
    id: 'simplify',
    name: 'Simplify',
    description: 'Explain in simpler terms',
    icon: <Lightbulb className="w-4 h-4" />
  },
  {
    id: 'critique',
    name: 'Critical Analysis',
    description: 'Analyze strengths and weaknesses',
    icon: <MessageSquare className="w-4 h-4" />
  },
  {
    id: 'action_items',
    name: 'Action Items',
    description: 'Extract actionable items',
    icon: <ClipboardList className="w-4 h-4" />
  }
]

interface TransformPanelProps {
  notebookId: string
  sourceId: string
  sourceTitle: string
  onClose: () => void
  onTransformComplete?: (result: any) => void
}

export default function TransformPanel({
  notebookId,
  sourceId,
  sourceTitle,
  onClose,
  onTransformComplete
}: TransformPanelProps) {
  const [selectedType, setSelectedType] = useState<string | null>(null)
  const [customPrompt, setCustomPrompt] = useState('')
  const [isTransforming, setIsTransforming] = useState(false)
  const [result, setResult] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)

  const handleTransform = async () => {
    if (!selectedType) return

    setIsTransforming(true)
    setError(null)
    setResult(null)

    try {
      const response = await fetch(
        `/api/notebooks/${notebookId}/sources/${sourceId}/transform`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          credentials: 'include',
          body: JSON.stringify({
            transformation: selectedType,
            model: 'mistral',
            custom_prompt: selectedType === 'custom' ? customPrompt : null
          })
        }
      )

      if (!response.ok) {
        throw new Error('Transformation failed')
      }

      const data = await response.json()
      setResult(data.transformed_content)
      onTransformComplete?.(data)
    } catch (err: any) {
      setError(err.message || 'Failed to transform content')
    } finally {
      setIsTransforming(false)
    }
  }

  const copyToClipboard = async () => {
    if (!result) return
    await navigator.clipboard.writeText(result)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-gray-900 rounded-xl border border-gray-700 max-w-2xl w-full max-h-[80vh] overflow-hidden flex flex-col">
        {/* Header */}
        <div className="p-4 border-b border-gray-700 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Sparkles className="w-5 h-5 text-purple-400" />
            <h2 className="text-lg font-semibold">Transform Source</h2>
          </div>
          <button
            onClick={onClose}
            className="p-2 hover:bg-gray-800 rounded-lg transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          <p className="text-sm text-gray-400">
            Transforming: <span className="text-white">{sourceTitle}</span>
          </p>

          {/* Transformation Types */}
          {!result && (
            <div className="grid grid-cols-2 gap-2">
              {TRANSFORMATION_TYPES.map((type) => (
                <button
                  key={type.id}
                  onClick={() => setSelectedType(type.id)}
                  className={`p-3 rounded-lg border text-left transition-all ${
                    selectedType === type.id
                      ? 'border-purple-500 bg-purple-500/10'
                      : 'border-gray-700 hover:border-gray-600 bg-gray-800/50'
                  }`}
                >
                  <div className="flex items-center gap-2 mb-1">
                    <span className={selectedType === type.id ? 'text-purple-400' : 'text-gray-400'}>
                      {type.icon}
                    </span>
                    <span className="font-medium text-sm">{type.name}</span>
                  </div>
                  <p className="text-xs text-gray-500">{type.description}</p>
                </button>
              ))}
            </div>
          )}

          {/* Custom Prompt (for custom transformation) */}
          {selectedType === 'custom' && !result && (
            <div>
              <label className="block text-sm text-gray-400 mb-2">Custom Prompt</label>
              <textarea
                value={customPrompt}
                onChange={(e) => setCustomPrompt(e.target.value)}
                placeholder="Enter your custom transformation instructions..."
                className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm resize-none h-24 focus:outline-none focus:ring-2 focus:ring-purple-500"
              />
            </div>
          )}

          {/* Error */}
          {error && (
            <div className="p-3 bg-red-500/10 border border-red-500/30 rounded-lg text-red-400 text-sm">
              {error}
            </div>
          )}

          {/* Result */}
          {result && (
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-medium text-gray-300">Result</h3>
                <button
                  onClick={copyToClipboard}
                  className="flex items-center gap-1 px-2 py-1 text-xs bg-gray-800 hover:bg-gray-700 rounded transition-colors"
                >
                  {copied ? (
                    <>
                      <CheckCircle className="w-3 h-3 text-green-400" />
                      Copied!
                    </>
                  ) : (
                    <>
                      <Copy className="w-3 h-3" />
                      Copy
                    </>
                  )}
                </button>
              </div>
              <div className="p-4 bg-gray-800 rounded-lg border border-gray-700 max-h-96 overflow-y-auto">
                <pre className="whitespace-pre-wrap text-sm text-gray-300">{result}</pre>
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="p-4 border-t border-gray-700 flex justify-end gap-2">
          {result ? (
            <button
              onClick={() => {
                setResult(null)
                setSelectedType(null)
              }}
              className="px-4 py-2 bg-purple-600 hover:bg-purple-700 rounded-lg transition-colors"
            >
              Transform Again
            </button>
          ) : (
            <>
              <button
                onClick={onClose}
                className="px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded-lg transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleTransform}
                disabled={!selectedType || isTransforming}
                className="px-4 py-2 bg-purple-600 hover:bg-purple-700 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg transition-colors flex items-center gap-2"
              >
                {isTransforming ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    Transforming...
                  </>
                ) : (
                  <>
                    <Sparkles className="w-4 h-4" />
                    Transform
                  </>
                )}
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  )
}

