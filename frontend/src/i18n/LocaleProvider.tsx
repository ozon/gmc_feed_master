import { useEffect, useMemo, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { DatesProvider } from '@mantine/dates';
import dayjs from 'dayjs';
import 'dayjs/locale/de';
import { registerRelativeTime } from './relativeTime';

registerRelativeTime();

export function LocaleProvider({ children }: { children: ReactNode }) {
  const { i18n } = useTranslation();
  const language = i18n.language;

  useEffect(() => {
    dayjs.locale(language);
    document.documentElement.lang = language;
  }, [language]);

  const settings = useMemo(
    () => ({ locale: language, firstDayOfWeek: language === 'de' ? 1 : 0 } as const),
    [language],
  );

  return <DatesProvider settings={settings}>{children}</DatesProvider>;
}
