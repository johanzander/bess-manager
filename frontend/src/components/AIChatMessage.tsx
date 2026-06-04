import React from 'react';
import type { ChatMessage } from '../hooks/useAIChat';

interface Props {
  message: ChatMessage;
  isStreaming?: boolean;
}

/** Minimal markdown-to-JSX: bold, inline code, code blocks, lists. */
function renderMarkdown(text: string): React.ReactNode[] {
  const nodes: React.ReactNode[] = [];
  const blocks = text.split(/```(\w*)\n?([\s\S]*?)```/g);

  for (let i = 0; i < blocks.length; i++) {
    if (i % 3 === 2) {
      // Code block content (index 2 of each triplet: lang, content, ...)
      nodes.push(
        <pre key={i} className="bg-gray-100 dark:bg-gray-900 rounded px-2 py-1.5 text-xs overflow-x-auto my-1 font-mono">
          <code>{blocks[i]}</code>
        </pre>
      );
    } else if (i % 3 === 0) {
      // Regular text (or language tag at index 1 — skip those)
      const segment = blocks[i];
      if (!segment) continue;

      // Split into lines for list handling.
      const lines = segment.split('\n');
      let currentList: React.ReactNode[] = [];
      let inList = false;

      for (let li = 0; li < lines.length; li++) {
        const line = lines[li];
        const listMatch = line.match(/^(\s*[-*]\s+)(.*)/);
        if (listMatch) {
          if (!inList) inList = true;
          currentList.push(<li key={li}>{inlineFormat(listMatch[2])}</li>);
        } else {
          if (inList) {
            nodes.push(<ul key={`ul-${i}-${li}`} className="list-disc list-inside my-1 space-y-0.5">{currentList}</ul>);
            currentList = [];
            inList = false;
          }
          if (line.trim()) {
            nodes.push(<p key={`p-${i}-${li}`} className="my-0.5">{inlineFormat(line)}</p>);
          }
        }
      }
      if (inList) {
        nodes.push(<ul key={`ul-${i}-end`} className="list-disc list-inside my-1 space-y-0.5">{currentList}</ul>);
      }
    }
    // Index 1 of each triplet is the language tag — skip.
  }

  return nodes;
}

/** Bold (**text**) and inline code (`code`). */
function inlineFormat(text: string): React.ReactNode {
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g);
  return parts.map((part, i) => {
    if (part.startsWith('**') && part.endsWith('**')) {
      return <strong key={i}>{part.slice(2, -2)}</strong>;
    }
    if (part.startsWith('`') && part.endsWith('`')) {
      return <code key={i} className="bg-gray-100 dark:bg-gray-900 px-1 py-0.5 rounded text-xs font-mono">{part.slice(1, -1)}</code>;
    }
    return part;
  });
}

export default function AIChatMessage({ message, isStreaming }: Props) {
  const isUser = message.role === 'user';

  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div
        className={`max-w-[85%] rounded-lg px-3 py-2 text-sm ${
          isUser
            ? 'bg-blue-500 text-white'
            : 'bg-gray-100 dark:bg-gray-700 text-gray-900 dark:text-gray-100'
        }`}
      >
        {isUser ? (
          <p className="whitespace-pre-wrap">{message.content}</p>
        ) : (
          <div className="space-y-0 leading-relaxed">
            {message.content ? renderMarkdown(message.content) : (
              isStreaming && (
                <span className="inline-flex gap-1">
                  <span className="h-1.5 w-1.5 rounded-full bg-gray-400 animate-bounce" style={{ animationDelay: '0ms' }} />
                  <span className="h-1.5 w-1.5 rounded-full bg-gray-400 animate-bounce" style={{ animationDelay: '150ms' }} />
                  <span className="h-1.5 w-1.5 rounded-full bg-gray-400 animate-bounce" style={{ animationDelay: '300ms' }} />
                </span>
              )
            )}
          </div>
        )}
      </div>
    </div>
  );
}
