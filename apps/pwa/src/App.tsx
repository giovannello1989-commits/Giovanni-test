import React from 'react';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';

import { AuthProvider, useAuth } from './auth/auth';
import { Login } from './pages/Login';
import { Otp } from './pages/Otp';
import { Swipe } from './pages/Swipe';
import { Slip } from './pages/Slip';
import { Profile } from './pages/Profile';

function Authed({ children }: { children: React.ReactNode }) {
  const { token } = useAuth();
  if (!token) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/otp" element={<Otp />} />
          <Route
            path="/"
            element={
              <Authed>
                <Swipe />
              </Authed>
            }
          />
          <Route
            path="/slip"
            element={
              <Authed>
                <Slip />
              </Authed>
            }
          />
          <Route
            path="/profile"
            element={
              <Authed>
                <Profile />
              </Authed>
            }
          />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
