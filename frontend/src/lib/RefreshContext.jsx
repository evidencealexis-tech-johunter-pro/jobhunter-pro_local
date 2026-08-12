import React, { createContext, useContext, useState, useCallback } from 'react';

const RefreshContext = createContext();

export function RefreshProvider({ children }) {
  const [tick, setTick] = useState(0);
  const refresh = useCallback(() => setTick(prev => prev + 1), []);
  return (
    <RefreshContext.Provider value={{ tick, refresh }}>
      {children}
    </RefreshContext.Provider>
  );
}

export function useRefresh() {
  return useContext(RefreshContext);
}