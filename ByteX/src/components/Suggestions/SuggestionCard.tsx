import React from 'react';
import { Sparkles, Check, X } from 'lucide-react';
import './SuggestionCard.css';

export interface ProactiveSuggestion {
  id: string;
  title: string;
  description: string;
  command: string;
  confidence?: number;
}

interface SuggestionCardProps {
  suggestion: ProactiveSuggestion | null;
  onAccept: (suggestion: ProactiveSuggestion) => void;
  onDismiss: (suggestion: ProactiveSuggestion) => void;
  disabled?: boolean;
}

export const SuggestionCard: React.FC<SuggestionCardProps> = ({
  suggestion,
  onAccept,
  onDismiss,
  disabled = false,
}) => {
  if (!suggestion) return null;

  return (
    <div className="bytex-suggestion-container animate-fade-in">
      <div className="bytex-suggestion-card">
        <div className="bytex-suggestion-header">
          <div className="bytex-suggestion-title-group">
            <Sparkles size={14} className="bytex-suggestion-sparkle-icon" />
            <span className="bytex-suggestion-badge">✦ Suggested</span>
            <span className="bytex-suggestion-title">{suggestion.title}</span>
          </div>
          <button
            type="button"
            className="bytex-suggestion-close-btn"
            onClick={() => onDismiss(suggestion)}
            title="Dismiss suggestion"
            disabled={disabled}
          >
            <X size={13} />
          </button>
        </div>

        <p className="bytex-suggestion-desc">{suggestion.description}</p>

        <div className="bytex-suggestion-actions">
          <button
            type="button"
            className="bytex-suggestion-btn bytex-suggestion-accept"
            onClick={() => onAccept(suggestion)}
            disabled={disabled}
          >
            <Check size={13} />
            <span>Yes, do this</span>
          </button>
          <button
            type="button"
            className="bytex-suggestion-btn bytex-suggestion-dismiss"
            onClick={() => onDismiss(suggestion)}
            disabled={disabled}
          >
            <span>Dismiss</span>
          </button>
        </div>
      </div>
    </div>
  );
};

export default SuggestionCard;
