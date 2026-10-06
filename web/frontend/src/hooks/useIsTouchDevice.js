import { useState, useEffect } from 'react';

export function useIsTouchDevice() {
  const [isTouchDevice, setIsTouchDevice] = useState(false);

  useEffect(() => {
    // Check if the device primarily uses touch (coarse pointer) and lacks hover capabilities
    const mediaQuery = window.matchMedia('(hover: none) and (pointer: coarse)');
    
    // Initial check
    setIsTouchDevice(mediaQuery.matches);

    // Listener for changes (e.g., if a user connects a mouse or resizes window across breakpoints)
    const handler = (e) => setIsTouchDevice(e.matches);
    
    // Fallback for older Safari versions which don't support addEventListener on MediaQueryList
    if (mediaQuery.addEventListener) {
      mediaQuery.addEventListener('change', handler);
      return () => mediaQuery.removeEventListener('change', handler);
    } else {
      mediaQuery.addListener(handler);
      return () => mediaQuery.removeListener(handler);
    }
  }, []);

  return isTouchDevice;
}
