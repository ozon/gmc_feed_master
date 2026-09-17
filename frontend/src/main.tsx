import './i18n';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import { installGlobalErrorHandlers } from './logging/logger';

installGlobalErrorHandlers();

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
