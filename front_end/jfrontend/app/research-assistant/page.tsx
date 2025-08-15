'use client';

import { useState } from 'react';
import { Search, BookOpen, Globe, Zap } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card } from '@/components/ui/card';

export default function ResearchAssistantPage() {
  const [query, setQuery] = useState('');
  const [isSearching, setIsSearching] = useState(false);
  const [results, setResults] = useState<any[]>([]);

  const handleSearch = async () => {
    if (!query.trim() || isSearching) return;
    
    setIsSearching(true);
    try {
      const response = await fetch('/api/web-search', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          query,
          maxResults: 10,
          extractContent: true
        }),
      });
      
      if (response.ok) {
        const data = await response.json();
        setResults(data.results || []);
      }
    } catch (error) {
      console.error('Research search failed:', error);
    } finally {
      setIsSearching(false);
    }
  };

  return (
    <div className="min-h-screen p-6">
      <div className="max-w-6xl mx-auto">
        {/* Header */}
        <div className="text-center mb-8">
          <div className="flex items-center justify-center space-x-3 mb-4">
            <Search className="w-8 h-8 text-blue-400" />
            <h1 className="text-4xl font-bold bg-gradient-to-r from-blue-400 to-cyan-300 bg-clip-text text-transparent">
              Research Assistant
            </h1>
          </div>
          <p className="text-gray-300 text-lg">
            Advanced web search and research capabilities powered by AI
          </p>
        </div>

        {/* Search Interface */}
        <Card className="bg-gray-900/50 backdrop-blur-sm border-blue-500/30 p-6 mb-8">
          <div className="flex space-x-4">
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  handleSearch();
                }
              }}
              placeholder="Enter your research query..."
              className="flex-1 bg-gray-800 border-gray-600 text-white placeholder-gray-400 focus:border-blue-500"
              disabled={isSearching}
            />
            <Button
              onClick={handleSearch}
              disabled={isSearching || !query.trim()}
              className="bg-blue-600 hover:bg-blue-700 text-white px-6"
            >
              {isSearching ? (
                <div className="w-5 h-5 animate-spin rounded-full border-2 border-white border-t-transparent" />
              ) : (
                <Search className="w-5 h-5" />
              )}
            </Button>
          </div>
        </Card>

        {/* Features Grid */}
        <div className="grid md:grid-cols-3 gap-6 mb-8">
          <Card className="bg-gray-900/50 backdrop-blur-sm border-blue-500/30 p-6">
            <div className="flex items-center space-x-3 mb-4">
              <Globe className="w-6 h-6 text-blue-400" />
              <h3 className="text-lg font-semibold">Web Search</h3>
            </div>
            <p className="text-gray-300 text-sm">
              Comprehensive web search using multiple sources and AI-powered analysis
            </p>
          </Card>

          <Card className="bg-gray-900/50 backdrop-blur-sm border-blue-500/30 p-6">
            <div className="flex items-center space-x-3 mb-4">
              <BookOpen className="w-6 h-6 text-green-400" />
              <h3 className="text-lg font-semibold">Content Analysis</h3>
            </div>
            <p className="text-gray-300 text-sm">
              Deep content extraction and analysis from articles and research papers
            </p>
          </Card>

          <Card className="bg-gray-900/50 backdrop-blur-sm border-blue-500/30 p-6">
            <div className="flex items-center space-x-3 mb-4">
              <Zap className="w-6 h-6 text-purple-400" />
              <h3 className="text-lg font-semibold">AI Insights</h3>
            </div>
            <p className="text-gray-300 text-sm">
              AI-powered synthesis and insights from multiple research sources
            </p>
          </Card>
        </div>

        {/* Results */}
        {results.length > 0 && (
          <div>
            <h2 className="text-2xl font-semibold mb-4">Search Results</h2>
            <div className="space-y-4">
              {results.map((result, index) => (
                <Card key={index} className="bg-gray-900/50 backdrop-blur-sm border-gray-700 p-4">
                  <div className="flex items-start justify-between">
                    <div className="flex-1">
                      <h3 className="text-lg font-medium text-blue-300 mb-2">
                        <a 
                          href={result.url} 
                          target="_blank" 
                          rel="noopener noreferrer"
                          className="hover:text-blue-200 transition-colors"
                        >
                          {result.title}
                        </a>
                      </h3>
                      <p className="text-gray-300 text-sm mb-2 line-clamp-3">
                        {result.snippet}
                      </p>
                      <div className="flex items-center space-x-2 text-xs text-gray-500">
                        <span>{new URL(result.url).hostname}</span>
                        <span>•</span>
                        <span>{result.source || 'Web'}</span>
                      </div>
                    </div>
                  </div>
                </Card>
              ))}
            </div>
          </div>
        )}

        {/* Getting Started */}
        {results.length === 0 && !isSearching && (
          <Card className="bg-gray-900/50 backdrop-blur-sm border-gray-700 p-8 text-center">
            <Search className="w-16 h-16 text-gray-500 mx-auto mb-4" />
            <h3 className="text-xl font-semibold mb-2">Ready to Research</h3>
            <p className="text-gray-400 mb-4">
              Enter a research query above to get started with AI-powered web search and analysis.
            </p>
            <div className="text-sm text-gray-500">
              Try searching for topics like: "latest AI developments", "climate change research", "quantum computing breakthroughs"
            </div>
          </Card>
        )}
      </div>
    </div>
  );
}