'use client';

import { useRef, useState, useEffect } from 'react';

import UnifiedChatInterface from '@/components/UnifiedChatInterface';
import CompactScreenShare   from '@/components/CompactScreenShare';
import MiscDisplay          from '@/components/MiscDisplay';
import SettingsModal        from '@/components/SettingsModal';
import ResearchAssistant    from '@/components/ResearchAssistant';

import { motion } from 'framer-motion';
import { Button } from '@/components/ui/button';
import { Swords, Gamepad2, Globe, Sparkles, Bot, Settings } from 'lucide-react';
import Link   from 'next/link';
import Aurora from '@/components/Aurora';
import { useUser } from '@/lib/auth/UserProvider';

export default function Home() {
  const [isLoaded,            setIsLoaded]            = useState(false);
  const [screenAnalysis,      setScreenAnalysis]      = useState('');
  const [showResearchAssistant, setShowResearchAssistant] = useState(false);
  const [showSettings,        setShowSettings]        = useState(false);
  const [screenAnalysisCallback, setScreenAnalysisCallback] =
    useState<(() => Promise<string>) | null>(null);
  const [isScreenSharing,     setIsScreenSharing]     = useState(false);

  const chatInterfaceRef = useRef<any>(null);

  useEffect(() => {
    setIsLoaded(true);
  }, []);

  const handleScreenAnalysis = (analysis: string) => setScreenAnalysis(analysis);

  const handleAnalyzeAndRespond = (response: string) => {
    chatInterfaceRef.current?.addAIMessage(response, 'Screen Analysis');
  };

  return (
    /* ─── TOP wrapper (unchanged) ─── */
    <div className="relative min-h-screen overflow-hidden">

      {/* ─── Aurora stretched over the viewport ─── */}
      <div className="fixed inset-0 -z-10 pointer-events-none select-none">
        <Aurora
          className="w-full h-full"
          colorStops={['#3A29FF', '#FF94B4', '#FF3232']}
          blend={0.4}
          amplitude={1.0}
          speed={0.6}
        />

        {/* Optional feather-out vignette so edges fade nicely */}
        <div
          className="absolute inset-0 bg-black/20 pointer-events-none
                     [mask-image:radial-gradient(ellipse_at_center,white,transparent_80%)]"
        />
      </div>

      {/* ─── Foreground UI wrapper ─── */}
      <div className="relative z-10 min-h-screen bg-black/40 backdrop-blur-sm">
        <div className="container mx-auto px-4 py-8">
          {/* Header */}
          <motion.div
            initial={{ opacity: 0, y: -20 }}
            animate={{ opacity: isLoaded ? 1 : 0, y: isLoaded ? 0 : -20 }}
            transition={{ duration: 0.8 }}
            className="text-center mb-8"
          >
            <div className="flex justify-between items-start mb-6">
              <div className="flex-1">
                <h1 className="text-6xl font-bold bg-gradient-to-r from-blue-400 to-cyan-300 bg-clip-text text-transparent mb-4">
                  JARVIS AI
                </h1>
                <p className="text-gray-300 text-lg mb-6">
                  Advanced AI Assistant with Intelligent Model Orchestration
                </p>
              </div>

              <Button
                onClick={() => setShowSettings(true)}
                variant="outline"
                size="sm"
                className="bg-gray-800 border-gray-600 text-gray-300 hover:bg-gray-700"
              >
                <Settings className="w-4 h-4 mr-2" />
                Settings
              </Button>
            </div>

            {/* Top buttons */}
            <div className="flex justify-center space-x-4 mb-8">
              <Link href="/versus-mode">
                <Button className="bg-gradient-to-r from-red-600 to-blue-600 hover:from-red-700 hover:to-blue-700 text-white px-6 py-3 text-lg">
                  <Swords className="w-5 h-5 mr-2" />
                  Versus Mode
                </Button>
              </Link>

              <Link href="/vibe-coding">
                <Button className="bg-gradient-to-r from-purple-600 to-pink-600 hover:from-purple-700 hover:to-pink-700 text-white px-6 py-3 text-lg">
                  <Sparkles className="w-5 h-5 mr-2" />
                  Vibe Coding
                </Button>
              </Link>

              <Link href="/ai-agents">
                <Button className="bg-gradient-to-r from-indigo-600 to-purple-600 hover:from-indigo-700 hover:to-purple-700 text-white px-6 py-3 text-lg">
                  <Bot className="w-5 h-5 mr-2" />
                  AI Agents
                </Button>
              </Link>

              <Link href="/ai-games">
                <Button className="bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-700 hover:to-teal-700 text-white px-6 py-3 text-lg">
                  <Gamepad2 className="w-5 h-5 mr-2" />
                  AI-Games
                </Button>
              </Link>

              <Button
                onClick={() => setShowResearchAssistant(!showResearchAssistant)}
                variant={showResearchAssistant ? 'default' : 'outline'}
                className={`${
                  showResearchAssistant
                    ? 'bg-green-600 hover:bg-green-700 text-white'
                    : 'border-green-500 text-green-400 hover:bg-green-500/10 bg-transparent'
                } px-6 py-3 text-lg`}
              >
                <Globe className="w-5 h-5 mr-2" />
                Research Assistant
              </Button>
            </div>
          </motion.div>

          {/* Main grid */}
          <div
            className={`grid gap-6 ${
              showResearchAssistant
                ? 'grid-cols-1 lg:grid-cols-2'
                : 'grid-cols-1 lg:grid-cols-3'
            }`}
          >
            {/* Chat */}
            <motion.div
              initial={{ opacity: 0, x: -50 }}
              animate={{ opacity: isLoaded ? 1 : 0, x: isLoaded ? 0 : -50 }}
              transition={{ duration: 0.8, delay: 0.2 }}
              className={showResearchAssistant ? 'lg:col-span-1' : 'lg:col-span-2'}
            >
              <UnifiedChatInterface
                ref={chatInterfaceRef}
              />
            </motion.div>

            {/* Right column */}
            {showResearchAssistant ? (
              <motion.div
                initial={{ opacity: 0, x: 50 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ duration: 0.8, delay: 0.4 }}
              >
                <ResearchAssistant />
              </motion.div>
            ) : (
              <motion.div
                initial={{ opacity: 0, x: 50 }}
                animate={{ opacity: isLoaded ? 1 : 0, x: isLoaded ? 0 : 50 }}
                transition={{ duration: 0.8, delay: 0.4 }}
                className="space-y-6"
              >
                <CompactScreenShare
                  onAnalysis={handleScreenAnalysis}
                  onAnalyzeAndRespond={handleAnalyzeAndRespond}
                />
                <MiscDisplay screenAnalysis={screenAnalysis} />
              </motion.div>
            )}
          </div>
        </div>

        {/* Settings modal (foreground) */}
        <SettingsModal
          isOpen={showSettings}
          onClose={() => setShowSettings(false)}
          context="dashboard"
        />
      </div>
    </div>
  );
}
