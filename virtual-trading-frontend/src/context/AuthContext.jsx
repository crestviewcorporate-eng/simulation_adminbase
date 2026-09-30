import React, { createContext, useContext, useState, useEffect } from 'react';

const AuthContext = createContext(null);

export const AuthProvider = ({ children }) => {
  const [token, setToken] = useState(() => localStorage.getItem('vtrade_token'));
  const [role, setRole] = useState(() => localStorage.getItem('vtrade_role'));
  const [userId, setUserId] = useState(() => localStorage.getItem('vtrade_user_id'));
  const [name, setName] = useState(() => localStorage.getItem('vtrade_name'));
  const [forcePasswordChange, setForcePasswordChange] = useState(() => {
    return localStorage.getItem('vtrade_force_pwd_change') === 'true';
  });
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const savedToken = localStorage.getItem('vtrade_token');
    const savedRole = localStorage.getItem('vtrade_role');
    const savedUserId = localStorage.getItem('vtrade_user_id');
    const savedName = localStorage.getItem('vtrade_name');
    const savedForce = localStorage.getItem('vtrade_force_pwd_change') === 'true';

    if (savedToken && savedRole && savedUserId) {
      setToken(savedToken);
      setRole(savedRole);
      setUserId(savedUserId);
      setName(savedName || savedUserId);
      setForcePasswordChange(savedForce);
    }
    setLoading(false);
  }, []);

  const login = (authToken, userRole, id, userName = '', mustChangePassword = false) => {
    localStorage.setItem('vtrade_token', authToken);
    localStorage.setItem('vtrade_role', userRole);
    localStorage.setItem('vtrade_user_id', id);
    localStorage.setItem('vtrade_force_pwd_change', String(mustChangePassword));
    if (userName) localStorage.setItem('vtrade_name', userName);

    setToken(authToken);
    setRole(userRole);
    setUserId(id);
    setName(userName || id);
    setForcePasswordChange(mustChangePassword);
  };

  const clearForcePasswordChange = () => {
    localStorage.setItem('vtrade_force_pwd_change', 'false');
    setForcePasswordChange(false);
  };

  const logout = () => {
    localStorage.removeItem('vtrade_token');
    localStorage.removeItem('vtrade_role');
    localStorage.removeItem('vtrade_user_id');
    localStorage.removeItem('vtrade_name');
    localStorage.removeItem('vtrade_force_pwd_change');

    setToken(null);
    setRole(null);
    setUserId(null);
    setName(null);
    setForcePasswordChange(false);
  };

  const value = {
    token,
    role,
    userId,
    name,
    forcePasswordChange,
    isAuthenticated: !!token,
    isAdmin: role === 'admin',
    isUser: role === 'user',
    loading,
    login,
    clearForcePasswordChange,
    logout,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};
