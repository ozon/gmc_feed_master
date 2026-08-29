import { useEffect, useState } from 'react';
import { Button, Group, PasswordInput, Select, Stack, TextInput } from '@mantine/core';
import { useForm } from '@tanstack/react-form';
import { useTranslation } from 'react-i18next';
import { useUpdateFeedSource } from '../../api/hooks';
import { ApiError } from '../../api/client';
import { notifyMutationError, notifySuccess } from '../../app/notifications';
import type { FeedSourceRow } from '../../api/types';

const CRON_PRESETS = [
  { value: '0 * * * *', labelKey: 'cron.presets.hourly' },
  { value: '0 0 * * *', labelKey: 'cron.presets.daily' },
  { value: '0 0 * * 0', labelKey: 'cron.presets.weekly' },
  { value: '0 0 1 * *', labelKey: 'cron.presets.monthly' },
] as const;

const SOURCE_FORMATS = ['xml', 'tsv', 'csv', 'wide_tsv'] as const;

type SettingsFormValues = {
  name: string;
  source_format: string;
  source_url: string;
  cron_expression: string;
  target_country: string;
  target_language: string;
  currency: string;
  volume_drop_threshold_pct: number;
  history_retention_count: number;
};

export function FeedSettingsForm({ feed }: { feed: FeedSourceRow }) {
  const { t } = useTranslation('setup');
  const { t: tCommon } = useTranslation('common');
  const updateFeedSource = useUpdateFeedSource();
  const [username, setUsername] = useState(() => {
    const cfg = feed.configuration as Record<string, unknown> | undefined;
    const ba = cfg?.basic_auth as Record<string, unknown> | undefined;
    return (ba?.username as string) ?? '';
  });
  const [password, setPassword] = useState('');
  const [serverError, setServerError] = useState<string | null>(null);

  const form = useForm({
    defaultValues: {
      name: feed.name,
      source_format: feed.source_format,
      source_url: feed.source_url ?? '',
      cron_expression: feed.cron_expression ?? '',
      target_country: feed.target_country ?? '',
      target_language: feed.target_language ?? '',
      currency: feed.currency ?? '',
      volume_drop_threshold_pct: feed.volume_drop_threshold_pct,
      history_retention_count: feed.history_retention_count,
    } as SettingsFormValues,
    onSubmit: async ({ value }) => {
      const payload: Record<string, unknown> = {};
      if (value.name !== feed.name) payload.name = value.name;
      if (value.source_format !== feed.source_format) payload.source_format = value.source_format;
      if (value.source_url !== (feed.source_url ?? '')) payload.source_url = value.source_url || null;
      if (value.cron_expression !== (feed.cron_expression ?? '')) payload.cron_expression = value.cron_expression || null;
      if (value.target_country !== (feed.target_country ?? '')) payload.target_country = value.target_country || null;
      if (value.target_language !== (feed.target_language ?? '')) payload.target_language = value.target_language || null;
      if (value.currency !== (feed.currency ?? '')) payload.currency = value.currency || null;
      if (value.volume_drop_threshold_pct !== feed.volume_drop_threshold_pct) payload.volume_drop_threshold_pct = value.volume_drop_threshold_pct;
      if (value.history_retention_count !== feed.history_retention_count) payload.history_retention_count = value.history_retention_count;

      const originalUsername =
        ((feed.configuration as Record<string, unknown> | undefined)?.basic_auth as Record<string, unknown> | undefined)?.username as string | undefined ?? '';
      if (username !== originalUsername || password) {
        const existingCfg = (feed.configuration ?? {}) as Record<string, unknown>;
        const existingBa = (existingCfg.basic_auth ?? {}) as Record<string, unknown>;
        payload.configuration = {
          ...existingCfg,
          basic_auth: {
            ...existingBa,
            username,
            ...(password ? { password } : {}),
          },
        };
      }

      try {
        setServerError(null);
        await updateFeedSource.mutateAsync({ id: feed.id, ...payload });
        notifySuccess(t('saved'));
      } catch (error) {
        if (error instanceof ApiError && error.status === 422 && error.detail) {
          setServerError(error.detail);
          notifyMutationError(error, t('saveFailed'));
        } else {
          notifyMutationError(error, t('saveFailed'));
        }
      }
    },
  });

  useEffect(() => {
    const cfg = feed.configuration as Record<string, unknown> | undefined;
    const ba = cfg?.basic_auth as Record<string, unknown> | undefined;
    setUsername((ba?.username as string) ?? '');
    setPassword('');
    setServerError(null);
  }, [feed]);

  const cronPresets = CRON_PRESETS.map((p) => ({
    value: p.value,
    label: t(p.labelKey),
  }));

  const formatData = SOURCE_FORMATS.map((f) => ({
    value: f,
    label: f.toUpperCase(),
  }));

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        void form.handleSubmit();
      }}
    >
      <Stack gap="md">
        {serverError && (
          <div role="alert" style={{ color: 'var(--mantine-color-red-6)' }}>
            {serverError}
          </div>
        )}
        <form.Field name="name">
          {(field) => (
            <TextInput
              label={t('fields.name')}
              value={field.state.value}
              onChange={(event) => field.handleChange(event.currentTarget.value)}
              withAsterisk
            />
          )}
        </form.Field>
        <form.Field name="source_format">
          {(field) => (
            <Select
              label={t('fields.sourceFormat')}
              data={formatData}
              value={field.state.value}
              onChange={(value) => field.handleChange(value ?? 'xml')}
              allowDeselect={false}
            />
          )}
        </form.Field>
        <form.Field name="source_url">
          {(field) => (
            <TextInput
              label={t('fields.sourceUrl')}
              value={field.state.value}
              onChange={(event) => field.handleChange(event.currentTarget.value)}
            />
          )}
        </form.Field>
        <form.Field name="cron_expression">
          {(field) => (
            <TextInput
              label={t('fields.cronExpression')}
              value={field.state.value}
              onChange={(event) => field.handleChange(event.currentTarget.value)}
              description={t('cron.utcHint')}
            />
          )}
        </form.Field>
        <Select
          label={t('cron.utcHint')}
          data={cronPresets}
          placeholder={t('fields.cronExpression')}
          onChange={(value) => {
            if (value) {
              form.setFieldValue('cron_expression', value);
            }
          }}
        />
        <form.Field name="target_country">
          {(field) => (
            <TextInput
              label={t('fields.targetCountry')}
              value={field.state.value}
              onChange={(event) => field.handleChange(event.currentTarget.value)}
            />
          )}
        </form.Field>
        <form.Field name="target_language">
          {(field) => (
            <TextInput
              label={t('fields.targetLanguage')}
              value={field.state.value}
              onChange={(event) => field.handleChange(event.currentTarget.value)}
            />
          )}
        </form.Field>
        <form.Field name="currency">
          {(field) => (
            <TextInput
              label={t('fields.currency')}
              value={field.state.value}
              onChange={(event) => field.handleChange(event.currentTarget.value)}
            />
          )}
        </form.Field>
        <form.Field name="volume_drop_threshold_pct">
          {(field) => (
            <TextInput
              label={t('fields.volumeDropThreshold')}
              type="number"
              min={0}
              max={100}
              value={String(field.state.value)}
              onChange={(event) => field.handleChange(Number(event.currentTarget.value))}
            />
          )}
        </form.Field>
        <form.Field name="history_retention_count">
          {(field) => (
            <TextInput
              label={t('fields.historyRetention')}
              type="number"
              min={1}
              value={String(field.state.value)}
              onChange={(event) => field.handleChange(Number(event.currentTarget.value))}
            />
          )}
        </form.Field>
        <TextInput
          label={t('basicAuth.username')}
          value={username}
          onChange={(event) => setUsername(event.currentTarget.value)}
        />
        <PasswordInput
          label={t('basicAuth.password')}
          placeholder={t('basicAuth.passwordPlaceholder')}
          value={password}
          onChange={(event) => setPassword(event.currentTarget.value)}
        />
        <form.Subscribe
          selector={(state) => ({ isDirty: state.isDirty })}
        >
          {({ isDirty }) => (
            <Group justify="flex-end" mt="sm">
              <Button variant="default" onClick={() => form.reset()} disabled={!isDirty}>
                {tCommon('actions.cancel')}
              </Button>
              <Button type="submit" loading={updateFeedSource.isPending} disabled={!isDirty}>
                {tCommon('actions.save')}
              </Button>
            </Group>
          )}
        </form.Subscribe>
      </Stack>
    </form>
  );
}
