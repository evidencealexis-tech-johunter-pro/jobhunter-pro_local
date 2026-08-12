import React, { useState, useEffect } from 'react';
import { Wifi, WifiOff } from 'lucide-react';

// Matches the same status-pill visual pattern already used elsewhere in
// this app (e.g. the "Active API key" / "No active API key" pills in
// Settings.jsx: rounded-full, px-2.5 py-1, colored bg + text pairing).
export default function OnlineStatusBadge() {
  const [browserOnline, setBrowserOnline] = useState(navigator.onLine);
  const [realOnline, setRealOnline] = useState(true);

  useEffect(() => {
    function handleOnline() { setBrowserOnline(true); checkRealConnectivity(); }
    function handleOffline() { setBrowserOnline(false); }

    window.addEventListener('online', handleOnline);
    window.addEventListener('offline', handleOffline);

    checkRealConnectivity();
    const interval = setInterval(checkRealConnectivity, 20000);

    return () => {
      window.removeEventListener('online', handleOnline);
      window.removeEventListener('offline', handleOffline);
      clearInterval(interval);
    };
  }, []);

  async function checkRealConnectivity() {
    try {
      const res = await fetch('/api/network-status');
      const data = await res.json();
      setRealOnline(!!data.online);
    } catch (e) {
      setRealOnline(false);
    }
  }

  const isOnline = browserOnline && realOnline;

  return (
    <div
      className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-full text-xs font-medium ${
        isOnline ? 'bg-emerald-50 text-emerald-600' : 'bg-red-50 text-red-600'
      }`}
      title={isOnline ? 'Connected to the internet' : 'No internet connection detected'}
    >
      {isOnline ? <Wifi className="w-3.5 h-3.5" /> : <WifiOff className="w-3.5 h-3.5" />}
      {isOnline ? 'Online' : 'Offline'}
    </div>
  );
}