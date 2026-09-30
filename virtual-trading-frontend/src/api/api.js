import axios from 'axios';

// Dynamic Base URL calculation:
// 1. Local Vite dev (port 5173) -> http://localhost:8000
// 2. Remote deployed server (port 9001, etc.) -> window.location.origin + '/api'
const getDynamicBaseUrl = () => {
  if (typeof window !== 'undefined') {
    if (window.location.port === '5173') {
      return 'http://localhost:8000';
    }
    return window.location.origin + '/api';
  }
  return '';
};

const api = axios.create({
  baseURL: getDynamicBaseUrl(),
  headers: {
    'Content-Type': 'application/json',
  },
  timeout: 30000,
});

api.interceptors.request.use(
  (config) => {
    config.baseURL = getDynamicBaseUrl();
    const token = localStorage.getItem('vtrade_token');
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => Promise.reject(error)
);

api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response && error.response.status === 401) {
      localStorage.removeItem('vtrade_token');
      localStorage.removeItem('vtrade_role');
      localStorage.removeItem('vtrade_user_id');
      localStorage.removeItem('vtrade_name');

      if (typeof window !== 'undefined' && !window.location.pathname.startsWith('/login')) {
        window.location.href = '/login?session_expired=true';
      }
    }
    return Promise.reject(error);
  }
);

export default api;
