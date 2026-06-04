import React, { useEffect, useRef, useState } from 'react';
import { Brain, X, RefreshCw } from 'lucide-react';
import { useAIChat } from '../hooks/useAIChat';
import AIChatMessage from './AIChatMessage';

export default function AIChatPanel() {
  const [open, setOpen] = useState(false);
  const [input, setInput] = useState('');
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const {
    messages,
    isStreaming,
    error,
    status,
    contextSummary,
    sendMessage,
    refreshContext,
    stopStreaming,
    clearChat,
  } = useAIChat();

  // Auto-scroll on new content.
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, open]);

  // Focus input when panel opens.
  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

  // Don't render anything if AI is not configured or not enabled.
  if (!status?.configured || !status?.enabled) return null;

  const handleSend = () => {
    const text = input.trim();
    if (!text || isStreaming) return;
    setInput('');
    sendMessage(text);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  // ── Collapsed: floating button ──────────────────────────────────────
  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="fixed bottom-5 right-5 z-50 h-12 w-12 rounded-full bg-blue-500 hover:bg-blue-600 text-white shadow-lg flex items-center justify-center transition-colors"
        title="Open AI Analyst"
      >
        <Brain className="h-6 w-6" />
      </button>
    );
  }

  // ── Expanded: chat panel ────────────────────────────────────────────
  return (
    <div className="fixed bottom-5 right-5 z-50 w-[400px] h-[540px] flex flex-col bg-white dark:bg-gray-800 rounded-xl shadow-2xl border border-gray-200 dark:border-gray-700 overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800/80">
        <div className="flex items-center gap-2">
          <Brain className="h-4 w-4 text-blue-500" />
          <span className="text-sm font-semibold text-gray-900 dark:text-white">BESS Analyst</span>
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={refreshContext}
            title="Refresh system context"
            className="p-1.5 rounded hover:bg-gray-200 dark:hover:bg-gray-700 text-gray-500 dark:text-gray-400 transition-colors"
          >
            <RefreshCw className="h-3.5 w-3.5" />
          </button>
          <button
            onClick={clearChat}
            title="Clear conversation"
            className="p-1.5 rounded hover:bg-gray-200 dark:hover:bg-gray-700 text-gray-500 dark:text-gray-400 transition-colors"
          >
            <X className="h-3.5 w-3.5" />
          </button>
          <button
            onClick={() => setOpen(false)}
            title="Close"
            className="p-1.5 rounded hover:bg-gray-200 dark:hover:bg-gray-700 text-gray-500 dark:text-gray-400 transition-colors"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      {/* Context summary */}
      {contextSummary && (
        <div className="px-4 py-1.5 text-[10px] text-gray-400 dark:text-gray-500 border-b border-gray-100 dark:border-gray-700/50 bg-gray-50/50 dark:bg-gray-800/40">
          {contextSummary}
        </div>
      )}

      {/* Messages */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-3 py-3 space-y-3">
        {messages.length === 0 && (
          <div className="text-center text-sm text-gray-400 dark:text-gray-500 mt-8 space-y-2">
            <Brain className="h-8 w-8 mx-auto opacity-30" />
            <p>Ask me about your battery system.</p>
            <p className="text-xs">
              Try: &quot;Why are savings lower than predicted?&quot;
            </p>
          </div>
        )}
        {messages.map((msg, i) => (
          <AIChatMessage
            key={i}
            message={msg}
            isStreaming={isStreaming && i === messages.length - 1 && msg.role === 'assistant'}
          />
        ))}
      </div>

      {/* Error banner */}
      {error && (
        <div className="px-3 py-2 bg-red-50 dark:bg-red-900/20 border-t border-red-200 dark:border-red-800 text-xs text-red-700 dark:text-red-300">
          {error}
        </div>
      )}

      {/* Input */}
      <div className="border-t border-gray-200 dark:border-gray-700 px-3 py-2">
        <div className="flex items-end gap-2">
          <textarea
            ref={inputRef}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask a question..."
            rows={1}
            className="flex-1 resize-none rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 px-3 py-2 text-sm text-gray-900 dark:text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500"
            style={{ maxHeight: '80px' }}
          />
          {isStreaming ? (
            <button
              onClick={stopStreaming}
              className="p-2 rounded-lg bg-red-500 hover:bg-red-600 text-white transition-colors flex-shrink-0"
              title="Stop"
            >
              <svg className="h-4 w-4" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="6" width="12" height="12" rx="1" /></svg>
            </button>
          ) : (
            <button
              onClick={handleSend}
              disabled={!input.trim()}
              className="p-2 rounded-lg bg-blue-500 hover:bg-blue-600 text-white disabled:opacity-40 disabled:cursor-not-allowed transition-colors flex-shrink-0"
              title="Send"
            >
              <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="22" y1="2" x2="11" y2="13" /><polygon points="22 2 15 22 11 13 2 9 22 2" /></svg>
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
