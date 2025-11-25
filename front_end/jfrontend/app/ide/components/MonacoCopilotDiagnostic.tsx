'use client'

/**
 * Diagnostic component to help debug Monaco inline suggestions
 * Add this temporarily to the IDE page to see what's happening
 */

import { useEffect } from 'react'
import * as monaco from 'monaco-editor'

interface DiagnosticProps {
  editor: monaco.editor.IStandaloneCodeEditor | null
}

export function MonacoCopilotDiagnostic({ editor }: DiagnosticProps) {
  useEffect(() => {
    if (!editor) return

    console.log('🔍 === COPILOT DIAGNOSTIC START ===')
    
    // Check if inline suggest is enabled
    const inlineSuggestConfig = editor.getOption(monaco.editor.EditorOption.inlineSuggest)
    console.log('📊 Inline Suggest Config:', inlineSuggestConfig)
    
    // Check if actions are available
    const triggerAction = editor.getAction('editor.action.inlineSuggest.trigger')
    const acceptAction = editor.getAction('editor.action.inlineSuggest.accept')
    const hideAction = editor.getAction('editor.action.inlineSuggest.hide')
    
    console.log('📊 Available Actions:', {
      trigger: {
        exists: !!triggerAction,
        supported: triggerAction?.isSupported?.() ?? 'unknown'
      },
      accept: {
        exists: !!acceptAction,
        supported: acceptAction?.isSupported?.() ?? 'unknown'
      },
      hide: {
        exists: !!hideAction,
        supported: hideAction?.isSupported?.() ?? 'unknown'
      }
    })
    
    // Check model and language
    const model = editor.getModel()
    if (model) {
      console.log('📊 Editor Model:', {
        language: model.getLanguageId(),
        uri: model.uri.toString(),
        valueLength: model.getValue().length
      })
    }
    
    // Try to manually trigger to see if it works
    console.log('🧪 Attempting manual trigger...')
    try {
      if (triggerAction && triggerAction.isSupported?.()) {
        triggerAction.run().then(() => {
          console.log('✅ Manual trigger completed')
        }).catch((err: any) => {
          console.error('❌ Manual trigger failed:', err)
        })
      } else {
        console.warn('⚠️ Trigger action not supported')
      }
    } catch (err) {
      console.error('❌ Manual trigger threw error:', err)
    }
    
    console.log('🔍 === COPILOT DIAGNOSTIC END ===')
    
  }, [editor])
  
  return null
}



