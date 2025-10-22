'use client';

import Link from 'next/link';
import { motion } from 'framer-motion';
import { Construction, ArrowLeft, Wrench, Code2, Sparkles } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import Aurora from '@/components/Aurora';

interface UnderConstructionProps {
  pageName: string;
  description?: string;
  expectedFeatures?: string[];
}

export default function UnderConstruction({
  pageName,
  description = "This feature is currently under active development.",
  expectedFeatures = []
}: UnderConstructionProps) {
  return (
    <div className="relative min-h-screen overflow-hidden">
      {/* Aurora Background */}
      <div className="fixed inset-0 -z-10 pointer-events-none select-none">
        <Aurora
          className="w-full h-full"
          colorStops={['#FF6B35', '#F7931E', '#FDC830']}
          blend={0.3}
          amplitude={0.8}
          speed={0.5}
        />
        <div className="absolute inset-0 bg-black/30 pointer-events-none [mask-image:radial-gradient(ellipse_at_center,white,transparent_80%)]" />
      </div>

      {/* Content */}
      <div className="relative z-10 min-h-screen bg-black/40 backdrop-blur-sm flex items-center justify-center p-4">
        <motion.div
          initial={{ opacity: 0, scale: 0.9, y: 20 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          transition={{ duration: 0.5 }}
          className="w-full max-w-2xl"
        >
          <Card className="bg-gray-900/70 backdrop-blur-md border-orange-500/30 p-8 md:p-12">
            {/* Icon Section */}
            <div className="flex justify-center mb-8">
              <motion.div
                animate={{
                  rotate: [0, 10, -10, 10, 0],
                }}
                transition={{
                  duration: 2,
                  repeat: Infinity,
                  repeatDelay: 3
                }}
                className="relative"
              >
                <div className="absolute inset-0 bg-orange-500/20 blur-xl rounded-full"></div>
                <div className="relative bg-orange-600/20 p-6 rounded-full border-2 border-orange-500/50">
                  <Construction className="w-16 h-16 text-orange-400" />
                </div>
              </motion.div>
            </div>

            {/* Title */}
            <motion.h1
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.2 }}
              className="text-4xl md:text-5xl font-bold text-center mb-4 bg-gradient-to-r from-orange-400 to-yellow-300 bg-clip-text text-transparent"
            >
              {pageName}
            </motion.h1>

            {/* Under Construction Badge */}
            <motion.div
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.3 }}
              className="flex justify-center mb-6"
            >
              <div className="flex items-center space-x-2 bg-orange-900/30 px-4 py-2 rounded-full border border-orange-500/30">
                <Wrench className="w-4 h-4 text-orange-400 animate-pulse" />
                <span className="text-orange-300 text-sm font-medium">Under Development</span>
              </div>
            </motion.div>

            {/* Description */}
            <motion.p
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.4 }}
              className="text-gray-300 text-center text-lg mb-8 leading-relaxed"
            >
              {description}
            </motion.p>

            {/* Expected Features */}
            {expectedFeatures.length > 0 && (
              <motion.div
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.5 }}
                className="mb-8 bg-gray-800/50 rounded-lg p-6 border border-gray-700"
              >
                <div className="flex items-center space-x-2 mb-4">
                  <Sparkles className="w-5 h-5 text-yellow-400" />
                  <h3 className="text-white font-semibold text-lg">Coming Soon</h3>
                </div>
                <ul className="space-y-2">
                  {expectedFeatures.map((feature, index) => (
                    <motion.li
                      key={index}
                      initial={{ opacity: 0, x: -10 }}
                      animate={{ opacity: 1, x: 0 }}
                      transition={{ delay: 0.6 + (index * 0.1) }}
                      className="flex items-center space-x-3 text-gray-300"
                    >
                      <Code2 className="w-4 h-4 text-orange-400 flex-shrink-0" />
                      <span>{feature}</span>
                    </motion.li>
                  ))}
                </ul>
              </motion.div>
            )}

            {/* Back Button */}
            <motion.div
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.7 }}
              className="flex justify-center"
            >
              <Link href="/">
                <Button
                  size="lg"
                  className="bg-gradient-to-r from-orange-600 to-yellow-600 hover:from-orange-700 hover:to-yellow-700 text-white font-semibold shadow-lg hover:shadow-orange-500/20 transition-all"
                >
                  <ArrowLeft className="w-5 h-5 mr-2" />
                  Back to Dashboard
                </Button>
              </Link>
            </motion.div>

            {/* Progress Indicator */}
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ delay: 0.8 }}
              className="mt-8 text-center"
            >
              <p className="text-gray-500 text-sm mb-3">Development Progress</p>
              <div className="w-full bg-gray-700 rounded-full h-2 overflow-hidden">
                <motion.div
                  initial={{ width: 0 }}
                  animate={{ width: "45%" }}
                  transition={{ delay: 1, duration: 1.5, ease: "easeOut" }}
                  className="bg-gradient-to-r from-orange-500 to-yellow-500 h-full rounded-full"
                />
              </div>
              <p className="text-gray-500 text-xs mt-2">Stay tuned for updates!</p>
            </motion.div>
          </Card>
        </motion.div>
      </div>
    </div>
  );
}
