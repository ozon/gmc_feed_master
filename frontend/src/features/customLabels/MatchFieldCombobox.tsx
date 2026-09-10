import { useTranslation } from 'react-i18next';
import { FieldSelect } from '../../components/FieldSelect';
import { buildFieldOptions, fromRegistryAttributes } from '../../api/fieldOptions';
import type { RegistryAttribute } from '../../api/types';

export function MatchFieldCombobox({
  value,
  onChange,
  attributes,
  disabled = false,
}: {
  value: string;
  onChange: (value: string) => void;
  attributes: RegistryAttribute[];
  disabled?: boolean;
}) {
  const { t } = useTranslation('customLabels');
  return (
    <FieldSelect
      value={value}
      onChange={onChange}
      options={buildFieldOptions(fromRegistryAttributes(attributes))}
      label={t('fields.matchField')}
      description={t('fields.matchFieldHint')}
      placeholder={t('fields.matchFieldPlaceholder')}
      disabled={disabled}
    />
  );
}
