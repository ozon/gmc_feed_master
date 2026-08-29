import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import LanguageDetector from 'i18next-browser-languagedetector';
import HttpBackend, { type HttpBackendOptions } from 'i18next-http-backend';

export const SUPPORTED_LANGUAGES = ['en', 'de'] as const;

export const initPromise = i18n
  .use(HttpBackend)
  .use(LanguageDetector)
  .use(initReactI18next)
  .init<HttpBackendOptions>({
    fallbackLng: 'en',
    supportedLngs: [...SUPPORTED_LANGUAGES],
    ns: ['common'],
    defaultNS: 'common',
    preload: ['common'],
    backend: {
      loadPath: '/locales/{{lng}}/{{ns}}.json',
      request: (_options, url, _payload, callback) => {
        void fetch(url)
          .then(async (response) => {
            if (!response.ok) {
              callback(new Error(`Failed to load ${url}: ${response.status}`), null);
              return;
            }
            callback(null, { status: response.status, data: await response.text() });
          })
          .catch((error: unknown) => {
            callback(error instanceof Error ? error : new Error(String(error)), null);
          });
      },
    },
    detection: {
      order: ['querystring', 'localStorage', 'navigator'],
      caches: ['localStorage'],
    },
    interpolation: {
      escapeValue: false,
    },
  });

export default i18n;
