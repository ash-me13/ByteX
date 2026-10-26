import { useEffect } from 'react';

interface KeyboardShortcutOptions {
  onFocusInput?: () => void;
  onEscape?: () => void;
}

export const useKeyboardShortcuts = ({ onFocusInput, onEscape }: KeyboardShortcutOptions) => {
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      // Ctrl + Space -> Focus Command Input
      if (event.ctrlKey && (event.code === 'Space' || event.key === ' ')) {
        event.preventDefault();
        onFocusInput?.();
      }

      // Escape -> Stop / Cancel Action
      if (event.key === 'Escape') {
        event.preventDefault();
        onEscape?.();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => {
      window.removeEventListener('keydown', handleKeyDown);
    };
  }, [onFocusInput, onEscape]);
};

export default useKeyboardShortcuts;
