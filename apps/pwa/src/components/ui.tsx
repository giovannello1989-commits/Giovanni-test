import React from 'react';

import { theme } from '../styles/theme';

export function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div
      style={{
        minHeight: '100vh',
        background: theme.colors.bg,
        display: 'flex',
        justifyContent: 'center',
      }}
    >
      <div style={{ width: '100%', maxWidth: 520, padding: theme.space(2) }}>{children}</div>
    </div>
  );
}

export function Card({ children }: { children: React.ReactNode }) {
  return (
    <div
      style={{
        background: theme.colors.bg2,
        border: `1px solid ${theme.colors.stroke}`,
        borderRadius: theme.radii.card,
        padding: theme.space(2),
      }}
    >
      {children}
    </div>
  );
}

export function Button({
  children,
  onClick,
  variant = 'primary',
  disabled,
}: {
  children: React.ReactNode;
  onClick?: () => void;
  variant?: 'primary' | 'ghost';
  disabled?: boolean;
}) {
  const base: React.CSSProperties = {
    height: 48,
    borderRadius: theme.radii.pill,
    padding: '0 16px',
    fontWeight: 900,
    letterSpacing: 0.2,
    border: variant === 'ghost' ? `1px solid ${theme.colors.stroke2}` : '1px solid transparent',
    background: variant === 'ghost' ? 'transparent' : theme.colors.accent,
    color: theme.colors.text,
    width: '100%',
    cursor: disabled ? 'not-allowed' : 'pointer',
    opacity: disabled ? 0.6 : 1,
  };

  return (
    <button style={base} onClick={disabled ? undefined : onClick}>
      {children}
    </button>
  );
}

export function Input(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...props}
      style={{
        width: '100%',
        height: 48,
        borderRadius: theme.radii.card,
        border: `1px solid ${theme.colors.stroke}`,
        background: theme.colors.bg2,
        color: theme.colors.text,
        padding: '0 14px',
        outline: 'none',
      }}
    />
  );
}

export function TopBar({ title, right }: { title: string; right?: React.ReactNode }) {
  return (
    <div style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', marginBottom: theme.space(2) }}>
      <div>
        <div style={{ fontSize: 18, fontWeight: 900 }}>{title}</div>
        <div style={{ marginTop: 4, color: theme.colors.subtext, fontSize: 12, fontWeight: 800 }}>Prematch only · Virtual credits</div>
      </div>
      {right}
    </div>
  );
}

export function BottomNav() {
  const path = location.pathname;
  const item = (href: string, label: string) => {
    const active = path === href;
    return (
      <a
        href={href}
        style={{
          flex: 1,
          textAlign: 'center',
          padding: '12px 8px',
          borderRadius: 16,
          background: active ? 'rgba(29,155,240,0.16)' : 'transparent',
          color: active ? theme.colors.text : theme.colors.subtext,
          fontWeight: 900,
          fontSize: 12,
          letterSpacing: 0.2,
        }}
      >
        {label}
      </a>
    );
  };

  return (
    <div
      style={{
        position: 'fixed',
        left: 0,
        right: 0,
        bottom: 0,
        display: 'flex',
        justifyContent: 'center',
        padding: 12,
        background: 'rgba(11,15,20,0.75)',
        backdropFilter: 'blur(12px)',
      }}
    >
      <div
        style={{
          width: '100%',
          maxWidth: 520,
          display: 'flex',
          gap: 8,
          border: `1px solid ${theme.colors.stroke}`,
          background: 'rgba(15,22,32,0.85)',
          borderRadius: 22,
          padding: 8,
        }}
      >
        {item('/', 'Swipe')}
        {item('/slip', 'Slip')}
        {item('/profile', 'Profile')}
      </div>
    </div>
  );
}
