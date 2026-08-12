import React, { useState } from 'react';
import { Outlet, NavLink } from 'react-router-dom';
import { Briefcase, LayoutDashboard, FileText, Search, Settings as SettingsIcon, Menu, X, GraduationCap, FolderOpen } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Toaster as SonnerToaster } from 'sonner';
import { RefreshProvider } from '@/lib/RefreshContext';
import OnlineStatusBadge from '@/components/OnlineStatusBadge';
import NotificationBell from '@/components/NotificationBell';

const navItems = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard },
  { to: '/resume', label: 'My Resume', icon: FileText },
  { to: '/jobs', label: 'Job Discovery', icon: Search },
  { to: '/upskill', label: 'Upskill', icon: GraduationCap },
  { to: '/context', label: 'Context Library', icon: FolderOpen },
  { to: '/settings', label: 'Settings', icon: SettingsIcon },
];

function SidebarContent({ onNavigate }) {
  return (
    <>
      <div className="px-5 py-5 border-b border-slate-800">
        <div className="flex items-center gap-2.5">
          <div className="w-9 h-9 rounded-lg bg-indigo-600 flex items-center justify-center shrink-0">
            <Briefcase className="w-5 h-5 text-white" />
          </div>
          <div>
            <h1 className="text-white font-semibold text-sm tracking-tight">JobHunter Pro</h1>
            <p className="text-slate-500 text-xs">Smart job matching</p>
          </div>
        </div>
      </div>
      <nav className="flex-1 px-3 py-4 space-y-1">
        {navItems.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.to === '/'}
            onClick={onNavigate}
            className={({ isActive }) =>
              `flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors ${
                isActive
                  ? 'bg-indigo-600 text-white'
                  : 'text-slate-400 hover:text-white hover:bg-slate-800'
              }`
            }
          >
            <item.icon className="w-4 h-4" />
            {item.label}
          </NavLink>
        ))}
      </nav>
      <div className="px-5 py-4 border-t border-slate-800">
        <p className="text-slate-600 text-xs leading-relaxed">
          Upload your resume once. JobHunter Pro finds matching openings and tells you exactly why each one fits.
        </p>
      </div>
    </>
  );
}

export default function Layout() {
  const [mobileOpen, setMobileOpen] = useState(false);

  return (
    <RefreshProvider>
      <div className="min-h-screen bg-slate-50">
        <SonnerToaster position="top-right" richColors closeButton />

        {/* Desktop sidebar */}
        <aside className="hidden lg:flex fixed inset-y-0 left-0 w-64 flex-col bg-slate-900 z-30">
          <SidebarContent />
        </aside>

        {/* Desktop top bar - new, holds the online status badge and
            notification bell in the top-right corner on every page */}
        <header className="hidden lg:flex lg:ml-64 sticky top-0 z-20 bg-white border-b border-slate-100 px-6 py-3 items-center justify-end gap-3">
          <OnlineStatusBadge />
          <NotificationBell />
        </header>

        {/* Mobile header - same two items added here, next to the menu button */}
        <header className="lg:hidden sticky top-0 z-30 bg-slate-900 text-white px-4 py-3 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-lg bg-indigo-600 flex items-center justify-center">
              <Briefcase className="w-4 h-4 text-white" />
            </div>
            <span className="font-semibold text-sm">JobHunter Pro</span>
          </div>
          <div className="flex items-center gap-2">
            <OnlineStatusBadge />
            <NotificationBell />
            <Button variant="ghost" size="icon" onClick={() => setMobileOpen(true)} className="text-white hover:bg-slate-800">
              <Menu className="w-5 h-5" />
            </Button>
          </div>
        </header>

        {/* Mobile drawer */}
        {mobileOpen && (
          <div className="lg:hidden fixed inset-0 z-50">
            <div className="absolute inset-0 bg-black/50" onClick={() => setMobileOpen(false)} />
            <aside className="absolute left-0 inset-y-0 w-64 bg-slate-900 flex flex-col">
              <div className="flex justify-end p-3">
                <Button variant="ghost" size="icon" onClick={() => setMobileOpen(false)} className="text-slate-400 hover:text-white">
                  <X className="w-5 h-5" />
                </Button>
              </div>
              <SidebarContent onNavigate={() => setMobileOpen(false)} />
            </aside>
          </div>
        )}

        {/* Main content */}
        <main className="lg:ml-64 min-h-screen">
          <Outlet />
        </main>
      </div>
    </RefreshProvider>
  );
}