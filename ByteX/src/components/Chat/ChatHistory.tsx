import React, { useEffect, useRef } from 'react';
import type { ChatMessage as ChatMessageType } from '../../types';
import ChatMessage from './ChatMessage';
import './ChatHistory.css';

interface ChatHistoryProps {
  messages: ChatMessageType[];
}

export const ChatHistory: React.FC<ChatHistoryProps> = ({ messages }) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const prevMessagesCountRef = useRef<number>(messages.length);
  const userScrolledUpRef = useRef<boolean>(false);

  const handleScroll = () => {
    if (!containerRef.current) return;
    const { scrollTop, scrollHeight, clientHeight } = containerRef.current;
    const distanceFromBottom = scrollHeight - scrollTop - clientHeight;
    // If user scrolled up by more than 100px, respect their scroll position
    userScrolledUpRef.current = distanceFromBottom > 100;
  };

  useEffect(() => {
    if (!containerRef.current) return;
    const el = containerRef.current;
    const isNewMessageCount = messages.length !== prevMessagesCountRef.current;
    prevMessagesCountRef.current = messages.length;

    // If a new message arrived, reset scroll-up lock and scroll to bottom
    if (isNewMessageCount) {
      userScrolledUpRef.current = false;
      el.scrollTo({
        top: el.scrollHeight,
        behavior: 'smooth',
      });
    } else if (!userScrolledUpRef.current) {
      // Streaming update while user is near bottom
      el.scrollTo({
        top: el.scrollHeight,
        behavior: 'smooth',
      });
    }
  }, [messages]);

  if (messages.length === 0) {
    return (
      <div className="bytex-chat-empty-state">
        <span className="bytex-empty-text">Ready when you are.</span>
      </div>
    );
  }

  // Deduplicate messages by ID to prevent duplicate render artifacts
  const seenIds = new Set<string>();
  const uniqueMessages = messages.filter((msg) => {
    if (seenIds.has(msg.id)) return false;
    seenIds.add(msg.id);
    return true;
  });

  return (
    <div
      ref={containerRef}
      className="bytex-chat-history-container"
      onScroll={handleScroll}
    >
      <div className="bytex-chat-messages-inner">
        {uniqueMessages.map((msg) => (
          <ChatMessage key={msg.id} message={msg} />
        ))}
      </div>
    </div>
  );
};

export default ChatHistory;
