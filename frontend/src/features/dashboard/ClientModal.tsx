import { useEffect } from 'react';
import { Button, Group, Modal, Select, Stack, TextInput } from '@mantine/core';
import { useForm } from '@tanstack/react-form';
import { useTranslation } from 'react-i18next';
import { useCreateClient, useUpdateClient } from '../../api/hooks';
import { ApiError } from '../../api/client';
import { notifyMutationError, notifySuccess } from '../../app/notifications';
import type { ClientSummary } from '../../api/types';

type ClientFormValues = { name: string; status: string };

export function ClientModal({
  opened,
  client,
  onClose,
}: {
  opened: boolean;
  client: ClientSummary | null;
  onClose: () => void;
}) {
  const { t } = useTranslation('dashboard');
  const { t: tCommon } = useTranslation('common');
  const createClient = useCreateClient();
  const updateClient = useUpdateClient();

  const form = useForm({
    defaultValues: { name: '', status: 'active' } as ClientFormValues,
    onSubmit: async ({ value }) => {
      try {
        if (client) {
          await updateClient.mutateAsync({ id: client.id, name: value.name, status: value.status });
        } else {
          await createClient.mutateAsync({ name: value.name, status: value.status });
        }
        notifySuccess(t('saved'));
        onClose();
      } catch (error) {
        if (error instanceof ApiError && error.status === 409) {
          notifyMutationError(error, t('duplicateName'));
          return;
        }
        notifyMutationError(error, t('saveFailed'));
      }
    },
  });

  useEffect(() => {
    if (opened) {
      form.reset({ name: client?.name ?? '', status: client?.status ?? 'active' });
    }
  }, [opened, client, form]);

  const mutationPending = client ? updateClient.isPending : createClient.isPending;

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title={client ? t('edit') : t('addClient')}
      centered
    >
      <form
        onSubmit={(event) => {
          event.preventDefault();
          void form.handleSubmit();
        }}
      >
        <Stack gap="md">
          <form.Field
            name="name"
            validators={{
              onChange: ({ value }) => (value.trim() ? undefined : t('clientModal.nameRequired')),
            }}
          >
            {(field) => (
              <TextInput
                label={t('clientModal.name')}
                value={field.state.value}
                onChange={(event) => field.handleChange(event.currentTarget.value)}
                error={field.state.meta.errors[0] as string | undefined}
                withAsterisk
              />
            )}
          </form.Field>
          <form.Field name="status">
            {(field) => (
              <Select
                label={t('clientModal.status')}
                data={[
                  { value: 'active', label: t('clientStatus.active') },
                  { value: 'paused', label: t('clientStatus.paused') },
                ]}
                value={field.state.value}
                onChange={(value) => field.handleChange(value ?? 'active')}
                allowDeselect={false}
              />
            )}
          </form.Field>
          <Group justify="flex-end" mt="sm">
            <Button type="submit" loading={mutationPending}>
              {tCommon('actions.save')}
            </Button>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
}
