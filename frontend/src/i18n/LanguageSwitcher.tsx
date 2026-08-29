import { Select } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { SUPPORTED_LANGUAGES } from './index';

export function LanguageSwitcher() {
  const { t, i18n } = useTranslation();

  return (
    <Select
      size="xs"
      w={110}
      aria-label={t('language.label')}
      data={SUPPORTED_LANGUAGES.map((lng) => ({ value: lng, label: t(`language.${lng}`) }))}
      value={i18n.language}
      onChange={(value) => {
        if (value) void i18n.changeLanguage(value);
      }}
      allowDeselect={false}
    />
  );
}
