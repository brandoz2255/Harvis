'use client'

import { motion, AnimatePresence } from 'framer-motion'
import { BookOpen, X } from 'lucide-react'
import { useNotebookPluginStore } from '@/stores/notebookPluginStore'

export default function NotebookPluginLauncher() {
  const { isOpen, toggle } = useNotebookPluginStore()

  return (
    <motion.button
      onClick={toggle}
      className="fixed bottom-6 right-6 z-40 hidden lg:flex items-center justify-center
                 w-12 h-12 rounded-full bg-primary text-primary-foreground shadow-lg
                 hover:shadow-xl glow-blue transition-shadow"
      whileHover={{ scale: 1.1 }}
      whileTap={{ scale: 0.95 }}
      title={isOpen ? 'Close Notebook' : 'Open Notebook'}
    >
      <AnimatePresence mode="wait" initial={false}>
        {isOpen ? (
          <motion.div
            key="close"
            initial={{ rotate: -90, opacity: 0 }}
            animate={{ rotate: 0, opacity: 1 }}
            exit={{ rotate: 90, opacity: 0 }}
            transition={{ duration: 0.15 }}
          >
            <X className="w-5 h-5" />
          </motion.div>
        ) : (
          <motion.div
            key="open"
            initial={{ rotate: 90, opacity: 0 }}
            animate={{ rotate: 0, opacity: 1 }}
            exit={{ rotate: -90, opacity: 0 }}
            transition={{ duration: 0.15 }}
          >
            <BookOpen className="w-5 h-5" />
          </motion.div>
        )}
      </AnimatePresence>
    </motion.button>
  )
}
