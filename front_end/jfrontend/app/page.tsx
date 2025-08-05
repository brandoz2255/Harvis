'use client';

import { useRef, useState, useEffect } from 'react';

import UnifiedChatInterface from '@/components/UnifiedChatInterface';
import CompactScreenShare   from '@/components/CompactScreenShare';
import MiscDisplay          from '@/components/MiscDisplay';
import SettingsModal        from '@/components/SettingsModal';

import { motion } from 'framer-motion';
import { Button } from '@/components/ui/button';
import { Settings } from 'lucide-react';
import Aurora from '@/components/Aurora';
import { useUser } from '@/lib/auth/UserProvider';

export default function Home() {
  const [isLoaded,            setIsLoaded]            = useState(false);
  const [screenAnalysis,      setScreenAnalysis]      = useState('');
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
            <div className="flex justify-center items-center mb-6">
              <div className="text-center">
                <h1 className="text-6xl font-bold bg-gradient-to-r from-blue-400 to-cyan-300 bg-clip-text text-transparent mb-4">
                  HARVIS AI
                </h1>
                <p className="text-gray-300 text-lg mb-6">
                  Advanced AI Assistant with Intelligent Model Orchestration
                </p>
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
            </div>

          </motion.div>

          {/* Main grid */}
          <div className="grid gap-6 grid-cols-1 lg:grid-cols-3">
            {/* Chat */}
            <motion.div
              initial={{ opacity: 0, x: -50 }}
              animate={{ opacity: isLoaded ? 1 : 0, x: isLoaded ? 0 : -50 }}
              transition={{ duration: 0.8, delay: 0.2 }}
              className="lg:col-span-2"
            >
              <UnifiedChatInterface
                ref={chatInterfaceRef}
              />
            </motion.div>

            {/* Right column */}
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
