import { useState } from 'react';
import {
  ActionIcon,
  Badge,
  Button,
  Group,
  Modal,
  MultiSelect,
  PasswordInput,
  Select,
  Stack,
  Switch,
  Table,
  TextInput,
  Title,
} from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { IconKey, IconPencil, IconPlus } from '@tabler/icons-react';
import {
  useAdminUsers,
  useClients,
  useCreateAdminUser,
  useResetUserPassword,
  useUpdateAdminUser,
} from '../../api/hooks';
import type { AdminUser } from '../../api/types';
import { LoadingState, ErrorState } from '../../components/StateViews';
import { notifyMutationError, notifySuccess } from '../../app/notifications';

type ClientOption = { value: string; label: string };

export function AdminUsersPage() {
  const { t } = useTranslation('admin');
  const usersQuery = useAdminUsers();
  const clientsQuery = useClients();
  const updateUser = useUpdateAdminUser();
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<AdminUser | null>(null);
  const [passwordUser, setPasswordUser] = useState<AdminUser | null>(null);

  if (usersQuery.isPending || clientsQuery.isPending) return <LoadingState />;
  if (usersQuery.isError || clientsQuery.isError) {
    return (
      <ErrorState
        onRetry={() => {
          void usersQuery.refetch();
          void clientsQuery.refetch();
        }}
      />
    );
  }

  const clientOptions: ClientOption[] = clientsQuery.data.map((c) => ({
    value: String(c.id),
    label: c.name,
  }));

  return (
    <Stack>
      <Group justify="space-between">
        <Title order={3}>{t('users.title')}</Title>
        <Button leftSection={<IconPlus size={16} />} onClick={() => setCreating(true)}>
          {t('users.add')}
        </Button>
      </Group>
      <Table striped data-testid="admin-users-table">
        <Table.Thead>
          <Table.Tr>
            <Table.Th>{t('users.columns.username')}</Table.Th>
            <Table.Th>{t('users.columns.role')}</Table.Th>
            <Table.Th>{t('users.columns.clients')}</Table.Th>
            <Table.Th>{t('users.columns.active')}</Table.Th>
            <Table.Th />
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {usersQuery.data.map((user) => (
            <Table.Tr key={user.id} data-testid={`user-row-${user.username}`}>
              <Table.Td>{user.username}</Table.Td>
              <Table.Td>
                <Badge variant="light" color={user.role === 'admin' ? 'grape' : 'blue'}>
                  {user.role === 'admin' ? t('users.roleAdmin') : t('users.roleUser')}
                </Badge>
              </Table.Td>
              <Table.Td>{user.client_ids?.length ?? 0}</Table.Td>
              <Table.Td>
                <Switch
                  aria-label={t('users.columns.active')}
                  checked={user.is_active}
                  onChange={(event) =>
                    updateUser.mutate({ id: user.id, is_active: event.currentTarget.checked })
                  }
                />
              </Table.Td>
              <Table.Td>
                <Group gap="xs" wrap="nowrap">
                  <ActionIcon
                    variant="subtle"
                    aria-label={t('users.edit')}
                    onClick={() => setEditing(user)}
                  >
                    <IconPencil size={16} />
                  </ActionIcon>
                  <ActionIcon
                    variant="subtle"
                    aria-label={t('users.resetPassword')}
                    onClick={() => setPasswordUser(user)}
                  >
                    <IconKey size={16} />
                  </ActionIcon>
                </Group>
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
      <UserModal
        key={editing?.id ?? 'new'}
        opened={creating || editing !== null}
        user={editing}
        clientOptions={clientOptions}
        onClose={() => {
          setCreating(false);
          setEditing(null);
        }}
      />
      <ResetPasswordModal user={passwordUser} onClose={() => setPasswordUser(null)} />
    </Stack>
  );
}

function UserModal({
  opened,
  user,
  clientOptions,
  onClose,
}: {
  opened: boolean;
  user: AdminUser | null;
  clientOptions: ClientOption[];
  onClose: () => void;
}) {
  const { t } = useTranslation('admin');
  const createUser = useCreateAdminUser();
  const updateUser = useUpdateAdminUser();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [role, setRole] = useState<'admin' | 'user'>(user?.role === 'admin' ? 'admin' : 'user');
  const [clientIds, setClientIds] = useState<string[]>(
    user ? (user.client_ids ?? []).map(String) : [],
  );

  function submit() {
    const clientIdsAsNumbers = clientIds.map(Number);
    const onSuccess = () => {
      notifySuccess(t('users.saved'));
      onClose();
    };
    const onError = (error: unknown) => notifyMutationError(error, t('users.saveFailed'));
    if (user) {
      updateUser.mutate(
        { id: user.id, role, client_ids: clientIdsAsNumbers },
        { onSuccess, onError },
      );
    } else {
      createUser.mutate(
        { username, password, role, client_ids: clientIdsAsNumbers },
        { onSuccess, onError },
      );
    }
  }

  return (
    <Modal opened={opened} onClose={onClose} title={user ? t('users.edit') : t('users.add')} centered>
      <Stack gap="md">
        {!user && (
          <>
            <TextInput
              label={t('users.columns.username')}
              value={username}
              onChange={(e) => setUsername(e.currentTarget.value)}
              required
            />
            <PasswordInput
              label={t('users.columns.password')}
              value={password}
              onChange={(e) => setPassword(e.currentTarget.value)}
              required
            />
          </>
        )}
        <Select
          label={t('users.columns.role')}
          data={[
            { value: 'user', label: t('users.roleUser') },
            { value: 'admin', label: t('users.roleAdmin') },
          ]}
          value={role}
          onChange={(value) => setRole(value === 'admin' ? 'admin' : 'user')}
          allowDeselect={false}
        />
        <MultiSelect
          label={t('users.columns.clients')}
          data={clientOptions}
          value={clientIds}
          onChange={setClientIds}
        />
        <Button
          onClick={submit}
          loading={createUser.isPending || updateUser.isPending}
          disabled={!user && (!username || !password)}
        >
          {t('users.save')}
        </Button>
      </Stack>
    </Modal>
  );
}

function ResetPasswordModal({ user, onClose }: { user: AdminUser | null; onClose: () => void }) {
  const { t } = useTranslation('admin');
  const resetPassword = useResetUserPassword();
  const [password, setPassword] = useState('');
  if (!user) return null;
  return (
    <Modal opened={user !== null} onClose={onClose} title={t('users.resetPassword')} centered>
      <Stack gap="md">
        <PasswordInput
          label={t('users.columns.password')}
          value={password}
          onChange={(e) => setPassword(e.currentTarget.value)}
          required
        />
        <Button
          loading={resetPassword.isPending}
          disabled={!password}
          onClick={() =>
            resetPassword.mutate(
              { id: user.id, newPassword: password },
              {
                onSuccess: () => {
                  notifySuccess(t('users.saved'));
                  onClose();
                },
                onError: (error) => notifyMutationError(error, t('users.saveFailed')),
              },
            )
          }
        >
          {t('users.save')}
        </Button>
      </Stack>
    </Modal>
  );
}
