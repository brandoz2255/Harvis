'use client'

import { useState, useEffect } from 'react'
import { motion } from 'framer-motion'
import { 
  Gamepad2, 
  Bot, 
  Trophy, 
  Play, 
  Pause, 
  RotateCcw, 
  Users, 
  Brain, 
  Zap,
  Target,
  Crown,
  ArrowLeft
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import Link from 'next/link'
import Aurora from '@/components/Aurora'

interface GameAgent {
  id: string
  name: string
  model: string
  strategy: string
  score: number
  wins: number
  losses: number
  status: 'idle' | 'thinking' | 'playing' | 'winner' | 'loser'
}

interface Game {
  id: string
  name: string
  description: string
  type: 'strategy' | 'puzzle' | 'creative' | 'logic'
  minPlayers: number
  maxPlayers: number
  status: 'available' | 'running' | 'completed'
  agents?: GameAgent[]
}

export default function AIGamesPage() {
  const [isLoaded, setIsLoaded] = useState(false)
  const [selectedGame, setSelectedGame] = useState<Game | null>(null)
  const [gameRunning, setGameRunning] = useState(false)
  const [agents, setAgents] = useState<GameAgent[]>([])

  useEffect(() => {
    setIsLoaded(true)
    // Initialize some demo agents
    setAgents([
      {
        id: '1',
        name: 'Strategic Alpha',
        model: 'llama3',
        strategy: 'Aggressive',
        score: 1250,
        wins: 8,
        losses: 2,
        status: 'idle'
      },
      {
        id: '2', 
        name: 'Logic Master',
        model: 'qwen2',
        strategy: 'Analytical',
        score: 1180,
        wins: 6,
        losses: 3,
        status: 'idle'
      },
      {
        id: '3',
        name: 'Creative Mind',
        model: 'gemini-flash',
        strategy: 'Adaptive',
        score: 1320,
        wins: 9,
        losses: 1,
        status: 'idle'
      }
    ])
  }, [])

  const availableGames: Game[] = [
    {
      id: 'tic-tac-toe',
      name: 'Tic-Tac-Toe',
      description: 'Classic strategy game where agents compete in optimal move selection',
      type: 'strategy',
      minPlayers: 2,
      maxPlayers: 2,
      status: 'available'
    },
    {
      id: 'word-association',
      name: 'Word Association Chain',
      description: 'Creative language game testing AI reasoning and vocabulary connections',
      type: 'creative',
      minPlayers: 2,
      maxPlayers: 4,
      status: 'available'
    },
    {
      id: 'logic-puzzle',
      name: 'Logic Puzzle Race',
      description: 'Mathematical and logical reasoning challenges for AI agents',
      type: 'logic',
      minPlayers: 1,
      maxPlayers: 6,
      status: 'available'
    },
    {
      id: 'story-building',
      name: 'Collaborative Story',
      description: 'AI agents work together to create coherent and creative narratives',
      type: 'creative',
      minPlayers: 2,
      maxPlayers: 4,
      status: 'available'
    },
    {
      id: 'chess-blitz',
      name: 'Speed Chess',
      description: 'Fast-paced chess matches testing strategic AI capabilities',
      type: 'strategy',
      minPlayers: 2,
      maxPlayers: 2,
      status: 'running'
    },
    {
      id: 'riddle-solve',
      name: 'Riddle Solving Contest',
      description: 'Complex riddles and puzzles to test AI reasoning abilities',
      type: 'puzzle',
      minPlayers: 1,
      maxPlayers: 8,
      status: 'available'
    }
  ]

  const getGameTypeColor = (type: Game['type']) => {
    switch (type) {
      case 'strategy': return 'border-red-500 text-red-400'
      case 'puzzle': return 'border-yellow-500 text-yellow-400'
      case 'creative': return 'border-purple-500 text-purple-400'
      case 'logic': return 'border-blue-500 text-blue-400'
      default: return 'border-gray-500 text-gray-400'
    }
  }

  const getStatusColor = (status: Game['status']) => {
    switch (status) {
      case 'available': return 'border-green-500 text-green-400'
      case 'running': return 'border-orange-500 text-orange-400'
      case 'completed': return 'border-gray-500 text-gray-400'
      default: return 'border-gray-500 text-gray-400'
    }
  }

  const getAgentStatusIcon = (status: GameAgent['status']) => {
    switch (status) {
      case 'thinking': return <Brain className="w-3 h-3 animate-pulse" />
      case 'playing': return <Zap className="w-3 h-3 text-yellow-400" />
      case 'winner': return <Crown className="w-3 h-3 text-yellow-400" />
      case 'loser': return <Target className="w-3 h-3 text-gray-400" />
      default: return <Bot className="w-3 h-3" />
    }
  }

  const startGame = () => {
    if (selectedGame) {
      setGameRunning(true)
      // Simulate game start
      setAgents(prev => prev.map(agent => ({
        ...agent,
        status: 'thinking'
      })))
    }
  }

  const stopGame = () => {
    setGameRunning(false)
    setAgents(prev => prev.map(agent => ({
      ...agent,
      status: 'idle'
    })))
  }

  return (
    <div className="relative min-h-screen overflow-hidden">
      {/* Aurora Background */}
      <div className="fixed inset-0 -z-10 pointer-events-none select-none">
        <Aurora
          className="w-full h-full"
          colorStops={['#10B981', '#3B82F6', '#8B5CF6']}
          blend={0.4}
          amplitude={1.0}
          speed={0.6}
        />
        <div className="absolute inset-0 bg-black/20 pointer-events-none [mask-image:radial-gradient(ellipse_at_center,white,transparent_80%)]" />
      </div>

      {/* Content */}
      <div className="relative z-10 min-h-screen bg-black/40 backdrop-blur-sm">
        <div className="container mx-auto px-4 py-8">
          {/* Header */}
          <motion.div
            initial={{ opacity: 0, y: -20 }}
            animate={{ opacity: isLoaded ? 1 : 0, y: isLoaded ? 0 : -20 }}
            transition={{ duration: 0.8 }}
            className="text-center mb-8"
          >
            <div className="flex items-center justify-between mb-6">
              <Link href="/">
                <Button variant="outline" className="bg-gray-800 border-gray-600 text-gray-300 hover:bg-gray-700">
                  <ArrowLeft className="w-4 h-4 mr-2" />
                  Back to Home
                </Button>
              </Link>

              <div className="flex-1 text-center">
                <h1 className="text-5xl font-bold bg-gradient-to-r from-emerald-400 to-teal-300 bg-clip-text text-transparent mb-4">
                  AI-Games Arena
                </h1>
                <p className="text-gray-300 text-lg">
                  Orchestrate AI Agents in Competitive Proof of Concept Games
                </p>
              </div>

              <div className="flex items-center space-x-2">
                <Badge variant="outline" className="border-emerald-500 text-emerald-400">
                  <Gamepad2 className="w-3 h-3 mr-1" />
                  {availableGames.filter(g => g.status === 'available').length} Games Available
                </Badge>
              </div>
            </div>
          </motion.div>

          {/* Main Content */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            {/* Available Games */}
            <motion.div
              initial={{ opacity: 0, x: -50 }}
              animate={{ opacity: isLoaded ? 1 : 0, x: isLoaded ? 0 : -50 }}
              transition={{ duration: 0.8, delay: 0.2 }}
              className="lg:col-span-2"
            >
              <Card className="bg-gray-900/50 backdrop-blur-sm border-emerald-500/30">
                <div className="p-4 border-b border-emerald-500/30">
                  <h3 className="text-xl font-semibold text-emerald-300">Available Games</h3>
                </div>
                <div className="p-4 space-y-4 max-h-96 overflow-y-auto">
                  {availableGames.map((game) => (
                    <motion.div
                      key={game.id}
                      className={`p-4 rounded-lg border cursor-pointer transition-all ${
                        selectedGame?.id === game.id
                          ? 'bg-emerald-900/30 border-emerald-500'
                          : 'bg-gray-800/50 border-gray-600 hover:border-emerald-500/50'
                      }`}
                      onClick={() => setSelectedGame(game)}
                      whileHover={{ scale: 1.02 }}
                      whileTap={{ scale: 0.98 }}
                    >
                      <div className="flex items-center justify-between mb-2">
                        <h4 className="text-lg font-medium text-white">{game.name}</h4>
                        <div className="flex items-center space-x-2">
                          <Badge variant="outline" className={`text-xs ${getGameTypeColor(game.type)}`}>
                            {game.type}
                          </Badge>
                          <Badge variant="outline" className={`text-xs ${getStatusColor(game.status)}`}>
                            {game.status}
                          </Badge>
                        </div>
                      </div>
                      <p className="text-gray-300 text-sm mb-2">{game.description}</p>
                      <div className="flex items-center justify-between text-xs text-gray-400">
                        <span>
                          <Users className="w-3 h-3 inline mr-1" />
                          {game.minPlayers === game.maxPlayers 
                            ? `${game.minPlayers} players` 
                            : `${game.minPlayers}-${game.maxPlayers} players`
                          }
                        </span>
                        {game.status === 'running' && (
                          <span className="text-orange-400 animate-pulse">Game in progress...</span>
                        )}
                      </div>
                    </motion.div>
                  ))}
                </div>
              </Card>
            </motion.div>

            {/* Agent Management & Game Control */}
            <motion.div
              initial={{ opacity: 0, x: 50 }}
              animate={{ opacity: isLoaded ? 1 : 0, x: isLoaded ? 0 : 50 }}
              transition={{ duration: 0.8, delay: 0.4 }}
              className="space-y-6"
            >
              {/* Game Control Panel */}
              <Card className="bg-gray-900/50 backdrop-blur-sm border-emerald-500/30">
                <div className="p-4 border-b border-emerald-500/30">
                  <h3 className="text-lg font-semibold text-emerald-300">Game Control</h3>
                </div>
                <div className="p-4 space-y-4">
                  {selectedGame ? (
                    <>
                      <div className="text-sm text-gray-300">
                        <p className="font-medium">{selectedGame.name}</p>
                        <p className="text-gray-400">{selectedGame.description}</p>
                      </div>
                      <div className="flex space-x-2">
                        {!gameRunning ? (
                          <Button
                            onClick={startGame}
                            className="flex-1 bg-emerald-600 hover:bg-emerald-700"
                            disabled={selectedGame.status === 'running'}
                          >
                            <Play className="w-4 h-4 mr-2" />
                            Start Game
                          </Button>
                        ) : (
                          <Button
                            onClick={stopGame}
                            className="flex-1 bg-red-600 hover:bg-red-700"
                          >
                            <Pause className="w-4 h-4 mr-2" />
                            Stop Game
                          </Button>
                        )}
                        <Button variant="outline" className="bg-gray-800 border-gray-600">
                          <RotateCcw className="w-4 h-4" />
                        </Button>
                      </div>
                    </>
                  ) : (
                    <p className="text-gray-400 text-center py-4">Select a game to start</p>
                  )}
                </div>
              </Card>

              {/* Active Agents */}
              <Card className="bg-gray-900/50 backdrop-blur-sm border-emerald-500/30">
                <div className="p-4 border-b border-emerald-500/30">
                  <h3 className="text-lg font-semibold text-emerald-300">AI Agents</h3>
                </div>
                <div className="p-4 space-y-3 max-h-64 overflow-y-auto">
                  {agents.map((agent) => (
                    <div
                      key={agent.id}
                      className="bg-gray-800/50 rounded-lg p-3 border border-gray-600"
                    >
                      <div className="flex items-center justify-between mb-2">
                        <div className="flex items-center space-x-2">
                          {getAgentStatusIcon(agent.status)}
                          <span className="text-sm font-medium text-white">{agent.name}</span>
                        </div>
                        <Badge variant="outline" className="text-xs border-blue-500 text-blue-400">
                          {agent.model}
                        </Badge>
                      </div>
                      <div className="text-xs text-gray-400 space-y-1">
                        <div className="flex justify-between">
                          <span>Strategy: {agent.strategy}</span>
                          <span>Score: {agent.score}</span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-green-400">Wins: {agent.wins}</span>
                          <span className="text-red-400">Losses: {agent.losses}</span>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </Card>

              {/* Leaderboard */}
              <Card className="bg-gray-900/50 backdrop-blur-sm border-emerald-500/30">
                <div className="p-4 border-b border-emerald-500/30">
                  <h3 className="text-lg font-semibold text-emerald-300">
                    <Trophy className="w-4 h-4 inline mr-2" />
                    Leaderboard
                  </h3>
                </div>
                <div className="p-4 space-y-2">
                  {agents
                    .sort((a, b) => b.score - a.score)
                    .map((agent, index) => (
                      <div
                        key={agent.id}
                        className="flex items-center justify-between text-sm"
                      >
                        <div className="flex items-center space-x-2">
                          <span className={`w-5 h-5 rounded-full flex items-center justify-center text-xs font-bold ${
                            index === 0 ? 'bg-yellow-500 text-black' :
                            index === 1 ? 'bg-gray-400 text-black' :
                            index === 2 ? 'bg-amber-600 text-white' :
                            'bg-gray-600 text-white'
                          }`}>
                            {index + 1}
                          </span>
                          <span className="text-gray-300">{agent.name}</span>
                        </div>
                        <span className="text-emerald-400 font-medium">{agent.score}</span>
                      </div>
                    ))}
                </div>
              </Card>
            </motion.div>
          </div>
        </div>
      </div>
    </div>
  )
}