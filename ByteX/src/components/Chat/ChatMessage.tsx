import React, { useState } from 'react';
import { Sparkles, AlertCircle, Copy, Check, ThumbsUp, ThumbsDown, RotateCw } from 'lucide-react';
import type { ChatMessage as ChatMessageType } from '../../types';
import './ChatMessage.css';

interface ChatMessageProps {
  message: ChatMessageType;
  onRegenerate?: (messageId: string) => void;
}

// Utility to sanitize raw tool calls, think tags, stack traces, and backend debug traces
export const sanitizeChatMessage = (text: string, role: string): string => {
  if (!text) return '';
  let cleaned = text;

  // 1. Strip <think>...</think> reasoning blocks
  cleaned = cleaned.replace(/<think>[\s\S]*?<\/think>/gi, '');

  // 2. Strip <tool>...</tool> blocks & standalone <tool> tags
  cleaned = cleaned.replace(/<tool>[\s\S]*?<\/tool>/gi, '');
  cleaned = cleaned.replace(/<\/?tool>/gi, '');

  // 3. Strip raw JSON tool payloads (e.g. {"tool": ...})
  cleaned = cleaned.replace(/\{"tool"\s*:\s*".*?"\s*,\s*"arguments"\s*:[\s\S]*?\}/gi, '');

  // 4. Strip Python stack traces if role is system/error
  if (role === 'system') {
    if (cleaned.includes('Traceback') || cleaned.includes('File "')) {
      cleaned = 'An unexpected error occurred. Please try again.';
    }
  }

  // 5. Clean internal STOP_SUCCESS / Step verification keywords if present
  cleaned = cleaned.replace(/STOP_SUCCESS/gi, '');
  cleaned = cleaned.replace(/verification\s*=\s*passed/gi, '');

  return cleaned.trim();
};

// Utility to convert Markdown formatted response to clean plain text for clipboard copying
export const markdownToPlainText = (markdown: string): string => {
  if (!markdown) return '';

  // 1. Separate code blocks to protect code content from text regex replacement
  const blocks = markdown.replace(/<br\s*\/?>/gi, '\n').split(/(```[\s\S]*?```)/g);

  const processedBlocks = blocks.map((block) => {
    // Code block: strip fences and optional language identifier
    if (block.startsWith('```') && block.endsWith('```')) {
      const inner = block.slice(3, -3).trim();
      const lines = inner.split('\n');
      if (lines.length > 1 && /^[a-zA-Z0-9_#+-]+$/.test(lines[0].trim())) {
        return lines.slice(1).join('\n');
      }
      return inner;
    }

    // Normal text block
    let text = block;

    // Headings: remove leading # markers
    text = text.replace(/^#{1,6}\s+(.+)$/gm, '$1');

    // Remove leading list bullets (- , * , • )
    text = text.replace(/^[\t ]*[-*•]\s+/gm, '');

    // Markdown links: [text](url) -> text
    text = text.replace(/\[(.*?)\]\((.*?)\)/g, '$1');

    // Bold + Italic: ***text*** or ___text___
    text = text.replace(/\*\*\*(.*?)\*\*\*/g, '$1');
    text = text.replace(/___(.*?)___/g, '$1');

    // Bold: **text** or __text__
    text = text.replace(/\*\*(.*?)\*\*/g, '$1');
    text = text.replace(/__(.*?)__/g, '$1');

    // Italic: *text* or _text_
    text = text.replace(/\*([^*\n]+)\*/g, '$1');
    text = text.replace(/_([^_\n]+)_/g, '$1');

    // Inline code: `code` -> code
    text = text.replace(/`([^`\n]+)`/g, '$1');

    // Strip remaining orphan asterisks / dashes / bullets
    text = text.replace(/^\s*[-*•]{1,3}\s*$/gm, '');

    // Strip remaining HTML tags
    text = text.replace(/<\/?[a-zA-Z0-9_-]+(\s+[^>]*)?>/g, '');

    return text;
  });

  return processedBlocks.join('\n').replace(/\n{3,}/g, '\n\n').trim();
};

// Utility to render inline formatted text (bold, italic, inline code, links)
const renderInlineFormatting = (text: string): React.ReactNode[] => {
  const clean = text.replace(/<br\s*\/?>/gi, '\n');
  // Match Markdown links [text](url), bold **text**, italic *text*, inline code `code`, and raw URLs
  const parts = clean.split(/(\[.*?\]\(.*?\)|\*\*.*?\*\*|\*.*?\*|`.*?`|https?:\/\/[^\s]+)/g);

  return parts.map((part, idx) => {
    // Markdown link: [label](url)
    const linkMatch = part.match(/^\[(.*?)\]\((.*?)\)$/);
    if (linkMatch) {
      return (
        <a
          key={idx}
          href={linkMatch[2]}
          target="_blank"
          rel="noopener noreferrer"
          className="bytex-chat-link"
        >
          {linkMatch[1]}
        </a>
      );
    }

    // Bare URL
    if (part.startsWith('http://') || part.startsWith('https://')) {
      return (
        <a
          key={idx}
          href={part}
          target="_blank"
          rel="noopener noreferrer"
          className="bytex-chat-link"
        >
          {part}
        </a>
      );
    }

    // Bold
    if (part.startsWith('**') && part.endsWith('**') && part.length >= 4) {
      return <strong key={idx} className="bytex-chat-strong">{part.slice(2, -2)}</strong>;
    }

    // Italic
    if (part.startsWith('*') && part.endsWith('*') && part.length >= 2) {
      return <em key={idx}>{part.slice(1, -1)}</em>;
    }

    // Inline Code
    if (part.startsWith('`') && part.endsWith('`') && part.length >= 2) {
      return <code key={idx} className="bytex-inline-code">{part.slice(1, -1)}</code>;
    }

    return part;
  });
};

// Component to parse structured Markdown, lists, headings, and clean paragraphs
const MarkdownRenderer: React.FC<{ content: string }> = ({ content }) => {
  if (!content) return null;

  const sanitized = content.replace(/<br\s*\/?>/gi, '\n');
  const blocks = sanitized.split(/(```[\s\S]*?```)/g);

  return (
    <div className="bytex-markdown-container">
      {blocks.map((block, bIdx) => {
        // Code block
        if (block.startsWith('```') && block.endsWith('```')) {
          const lines = block.slice(3, -3).trim().split('\n');
          const firstLine = lines[0].trim();
          const hasLang = /^[a-zA-Z0-9_-]+$/.test(firstLine);
          const lang = hasLang ? firstLine : '';
          const codeContent = hasLang ? lines.slice(1).join('\n') : lines.join('\n');

          return (
            <div key={bIdx} className="bytex-code-block">
              {lang && (
                <div className="bytex-code-header">
                  <span>{lang}</span>
                  <button
                    type="button"
                    className="bytex-code-copy-btn"
                    onClick={() => navigator.clipboard.writeText(codeContent)}
                    title="Copy code"
                  >
                    <Copy size={12} />
                  </button>
                </div>
              )}
              <pre className="bytex-code-body">
                <code>{codeContent}</code>
              </pre>
            </div>
          );
        }

        // Normal text block
        const lines = block.split('\n');
        const elements: React.ReactNode[] = [];
        let i = 0;

        while (i < lines.length) {
          const line = lines[i];
          const trimmed = line.trim();

          if (!trimmed || trimmed === '*' || trimmed === '-' || trimmed === '•' || trimmed === '***' || trimmed === '---') {
            i++;
            continue;
          }

          // Heading
          if (trimmed.startsWith('#### ')) {
            elements.push(<h4 key={`h4_${i}`} className="bytex-chat-heading">{renderInlineFormatting(trimmed.slice(5))}</h4>);
            i++;
            continue;
          }
          if (trimmed.startsWith('### ')) {
            elements.push(<h3 key={`h3_${i}`} className="bytex-chat-heading">{renderInlineFormatting(trimmed.slice(4))}</h3>);
            i++;
            continue;
          }
          if (trimmed.startsWith('## ')) {
            elements.push(<h2 key={`h2_${i}`} className="bytex-chat-heading">{renderInlineFormatting(trimmed.slice(3))}</h2>);
            i++;
            continue;
          }

          // Bullet List (- , * , • )
          if (/^[-*•]\s+/.test(trimmed)) {
            const listItems: string[] = [];
            while (i < lines.length && /^[-*•]\s+/.test(lines[i].trim())) {
              listItems.push(lines[i].trim().replace(/^[-*•]\s+/, ''));
              i++;
            }
            elements.push(
              <ul key={`ul_${i}`} className="bytex-chat-list">
                {listItems.map((item, lIdx) => (
                  <li key={lIdx}>{renderInlineFormatting(item)}</li>
                ))}
              </ul>
            );
            continue;
          }

          // Numbered List
          if (/^\d+\.\s+/.test(trimmed)) {
            const listItems: string[] = [];
            while (i < lines.length && /^\d+\.\s+/.test(lines[i].trim())) {
              listItems.push(lines[i].trim().replace(/^\d+\.\s+/, ''));
              i++;
            }
            elements.push(
              <ol key={`ol_${i}`} className="bytex-chat-list">
                {listItems.map((item, lIdx) => (
                  <li key={lIdx}>{renderInlineFormatting(item)}</li>
                ))}
              </ol>
            );
            continue;
          }

          // Normal Paragraph
          elements.push(
            <p key={`p_${i}`} className="bytex-chat-paragraph">
              {renderInlineFormatting(line)}
            </p>
          );
          i++;
        }

        return <React.Fragment key={bIdx}>{elements}</React.Fragment>;
      })}
    </div>
  );
};

export const ChatMessage: React.FC<ChatMessageProps> = ({ message, onRegenerate }) => {
  const [copied, setCopied] = useState<boolean>(false);
  const [feedback, setFeedback] = useState<'liked' | 'disliked' | null>(null);

  const cleanContent = sanitizeChatMessage(message.content, message.role);
  if (!cleanContent) return null;

  const timeFormatted = new Date(message.timestamp).toLocaleTimeString([], {
    hour: '2-digit',
    minute: '2-digit',
  });

  const isAssistant = message.role === 'assistant';
  const isSystem = message.role === 'system';

  const handleCopy = async () => {
    try {
      const plainText = markdownToPlainText(cleanContent);
      await navigator.clipboard.writeText(plainText);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // fallback
    }
  };

  const handleToggleLike = () => {
    setFeedback((prev) => (prev === 'liked' ? null : 'liked'));
  };

  const handleToggleDislike = () => {
    setFeedback((prev) => (prev === 'disliked' ? null : 'disliked'));
  };

  return (
    <div className={`bytex-chat-message ${message.role}`}>
      {/* Role Indicator Header for Assistant */}
      {isAssistant && (
        <div className="bytex-chat-sender-header">
          <div className="bytex-sender-avatar">
            <Sparkles size={13} className="bytex-badge-sparkle" />
          </div>
          <span className="bytex-sender-name">ByteX</span>
          <span className="bytex-chat-header-time">{timeFormatted}</span>
        </div>
      )}

      {/* Role Indicator Header for System */}
      {isSystem && (
        <div className="bytex-chat-sender-header system">
          <span className="bytex-sender-badge system">
            <AlertCircle size={11} />
            System
          </span>
          <span className="bytex-chat-header-time">{timeFormatted}</span>
        </div>
      )}

      {/* Floating Message Body */}
      <div className="bytex-chat-bubble-content">
        <MarkdownRenderer content={cleanContent} />
      </div>

      {/* Message Actions Bar for Assistant Responses */}
      {isAssistant && (
        <div className="bytex-message-actions-bar">
          <button
            type="button"
            className={`bytex-action-btn ${copied ? 'action-active' : ''}`}
            onClick={handleCopy}
            title={copied ? 'Copied to clipboard' : 'Copy message'}
            aria-label="Copy message"
          >
            {copied ? <Check size={13} className="action-icon-check" /> : <Copy size={13} />}
            {copied && <span className="bytex-action-label">Copied</span>}
          </button>

          <button
            type="button"
            className={`bytex-action-btn ${feedback === 'liked' ? 'action-active' : ''}`}
            onClick={handleToggleLike}
            title="Good response"
            aria-label="Thumbs up"
          >
            <ThumbsUp size={13} />
          </button>

          <button
            type="button"
            className={`bytex-action-btn ${feedback === 'disliked' ? 'action-active' : ''}`}
            onClick={handleToggleDislike}
            title="Bad response"
            aria-label="Thumbs down"
          >
            <ThumbsDown size={13} />
          </button>

          {onRegenerate && (
            <button
              type="button"
              className="bytex-action-btn"
              onClick={() => onRegenerate(message.id)}
              title="Regenerate response"
              aria-label="Regenerate"
            >
              <RotateCw size={13} />
            </button>
          )}
        </div>
      )}

      {/* Timestamp for User Message */}
      {!isAssistant && !isSystem && (
        <div className="bytex-chat-meta">
          <span>{timeFormatted}</span>
        </div>
      )}
    </div>
  );
};

export default ChatMessage;
