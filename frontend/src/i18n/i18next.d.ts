import 'i18next';
import type admin from '../../public/locales/en/admin.json';
import type auth from '../../public/locales/en/auth.json';
import type category from '../../public/locales/en/category.json';
import type common from '../../public/locales/en/common.json';
import type customLabels from '../../public/locales/en/customLabels.json';
import type dashboard from '../../public/locales/en/dashboard.json';
import type exportNs from '../../public/locales/en/export.json';
import type filter from '../../public/locales/en/filter.json';
import type mapping from '../../public/locales/en/mapping.json';
import type monitoring from '../../public/locales/en/monitoring.json';
import type pipeline from '../../public/locales/en/pipeline.json';
import type plugins from '../../public/locales/en/plugins.json';
import type products from '../../public/locales/en/products.json';
import type rules from '../../public/locales/en/rules.json';
import type setup from '../../public/locales/en/setup.json';
import type notifications from '../../public/locales/en/notifications.json';

declare module 'i18next' {
  interface CustomTypeOptions {
    defaultNS: 'common';
    resources: {
      admin: typeof admin;
      auth: typeof auth;
      common: typeof common;
      category: typeof category;
      customLabels: typeof customLabels;
      dashboard: typeof dashboard;
      export: typeof exportNs;
      filter: typeof filter;
      mapping: typeof mapping;
      monitoring: typeof monitoring;
      notifications: typeof notifications;
      pipeline: typeof pipeline;
      plugins: typeof plugins;
      products: typeof products;
      rules: typeof rules;
      setup: typeof setup;
    };
  }
}
