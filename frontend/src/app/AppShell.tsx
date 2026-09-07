import { useMemo, useState, type ComponentType, type FormEvent } from 'react';
import {
  ActionIcon,
  Anchor,
  AppShell as MantineAppShell,
  Burger,
  Button,
  Group,
  Menu,
  Modal,
  NavLink,
  PasswordInput,
  Stack,
  Text,
  Title,
  UnstyledButton,
  useComputedColorScheme,
  useMantineColorScheme,
} from '@mantine/core';
import { useDisclosure } from '@mantine/hooks';
import {
  IconActivity,
  IconBox,
  IconChevronDown,
  IconDashboard,
  IconFileExport,
  IconGitBranch,
  IconLogout,
  IconMoon,
  IconSettings,
  IconSun,
} from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import { Link, Outlet, useLocation, useNavigate, useParams } from 'react-router';
import { useChangePassword, useDashboardSummary, useLogout, usePlugins, useSession } from '../api/hooks';
import { getPluginIcon } from '../components/PluginIconMap';
import { LanguageSwitcher } from '../i18n/LanguageSwitcher';
import { notifyError, notifyMutationError, notifySuccess } from './notifications';

function ColorSchemeToggle() {
  const { t } = useTranslation();
  const { setColorScheme } = useMantineColorScheme();
  const computed = useComputedColorScheme('light');
  return (
    <ActionIcon
      variant="default"
      aria-label={computed === 'dark' ? t('colorScheme.toLight') : t('colorScheme.toDark')}
      onClick={() => setColorScheme(computed === 'dark' ? 'light' : 'dark')}
    >
      {computed === 'dark' ? <IconSun size={16} /> : <IconMoon size={16} />}
    </ActionIcon>
  );
}

function ChangePasswordModal({ opened, onClose }: { opened: boolean; onClose: () => void }) {
  const { t } = useTranslation('auth');
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [confirm, setConfirm] = useState('');
  const [mismatch, setMismatch] = useState(false);
  const mutation = useChangePassword();

  function submit(event: FormEvent<HTMLElement>) {
    event.preventDefault();
    if (next !== confirm) {
      setMismatch(true);
      return;
    }
    setMismatch(false);
    mutation.mutate(
      { currentPassword: current, newPassword: next },
      {
        onSuccess: () => {
          notifySuccess(t('passwordChange.success'));
          onClose();
        },
        onError: (error) => notifyMutationError(error, t('passwordChange.error')),
      },
    );
  }

  return (
    <Modal opened={opened} onClose={onClose} title={t('passwordChange.title')} centered>
      <Stack component="form" onSubmit={submit} gap="md">
        <PasswordInput
          label={t('passwordChange.current')}
          value={current}
          onChange={(event) => setCurrent(event.currentTarget.value)}
          autoComplete="current-password"
          required
        />
        <PasswordInput
          label={t('passwordChange.next')}
          value={next}
          onChange={(event) => setNext(event.currentTarget.value)}
          autoComplete="new-password"
          required
        />
        <PasswordInput
          label={t('passwordChange.confirm')}
          value={confirm}
          onChange={(event) => setConfirm(event.currentTarget.value)}
          error={mismatch ? t('passwordChange.mismatch') : undefined}
          autoComplete="new-password"
          required
        />
        <Button type="submit" loading={mutation.isPending}>
          {t('passwordChange.submit')}
        </Button>
      </Stack>
    </Modal>
  );
}

function UserMenu() {
  const { t } = useTranslation();
  const { data: user } = useSession();
  const logoutMutation = useLogout();
  const navigate = useNavigate();
  const [passwordOpened, { open: openPassword, close: closePassword }] = useDisclosure(false);

  return (
    <>
      <Menu shadow="md" width={200} position="bottom-end">
        <Menu.Target>
          <UnstyledButton aria-label={user?.username ?? 'user'}>
            <Group gap={4}>
              <Text size="sm">{user?.username}</Text>
              <IconChevronDown size={14} />
            </Group>
          </UnstyledButton>
        </Menu.Target>
        <Menu.Dropdown>
          <Menu.Item leftSection={<IconSettings size={14} />} onClick={openPassword}>
            {t('actions.changePassword')}
          </Menu.Item>
          <Menu.Item
            leftSection={<IconLogout size={14} />}
            onClick={() =>
              logoutMutation.mutate(undefined, {
                onSuccess: () => navigate('/login'),
                onError: (error) => notifyMutationError(error, t('errors.logoutFailed')),
              })
            }
          >
            {t('actions.logout')}
          </Menu.Item>
        </Menu.Dropdown>
      </Menu>
      <ChangePasswordModal opened={passwordOpened} onClose={closePassword} />
    </>
  );
}

function FeedBreadcrumb() {
  const { t } = useTranslation();
  const { clientId, feedSourceId } = useParams();
  const location = useLocation();
  const { data: summary } = useDashboardSummary();

  const client = summary?.clients?.find((entry) => String(entry.id) === clientId);
  const feed = client?.feed_sources?.find((entry) => String(entry.id) === feedSourceId);
  const area =
    /^\/clients\/[^/]+\/feeds\/[^/]+\/([^/?]+)/.exec(location.pathname)?.[1] ?? 'setup';

  if (!clientId) return null;

  return (
    <Group gap={4}>
      <Anchor component={Link} to="/" size="sm" c="dimmed" underline="never">
        {client?.name ?? t('breadcrumbs.selectClient')}
      </Anchor>
      <Text size="sm" c="dimmed">
        ›
      </Text>
      <Menu shadow="md" width={220} position="bottom-start">
        <Menu.Target>
          <UnstyledButton aria-label={t('breadcrumbs.selectFeed')}>
            <Group gap={4}>
              <Text size="sm">{feed?.name ?? t('breadcrumbs.selectFeed')}</Text>
              <IconChevronDown size={14} />
            </Group>
          </UnstyledButton>
        </Menu.Target>
        <Menu.Dropdown>
          {(client?.feed_sources ?? []).map((entry) => (
            <Menu.Item
              key={entry.id}
              component={Link}
              to={`/clients/${clientId}/feeds/${entry.id}/${area}${location.search}`}
            >
              {entry.name}
            </Menu.Item>
          ))}
        </Menu.Dropdown>
      </Menu>
    </Group>
  );
}

export function AppShell() {
  const { t } = useTranslation();
  const [opened, { toggle, close }] = useDisclosure();
  const location = useLocation();
  const { clientId, feedSourceId } = useParams();

  const feedBase = clientId && feedSourceId ? `/clients/${clientId}/feeds/${feedSourceId}` : null;

  const { data: plugins } = usePlugins();

  const pluginNavItems = useMemo(
    () =>
      (Array.isArray(plugins) ? plugins : [])
        .filter((p) => p.enabled && p.manifest?.frontend?.component)
        .map((p) => ({
          to: `${feedBase}/plugins/${p.id}`,
          label: t(`pluginNames.${p.id}`, { defaultValue: p.name }),
          icon: getPluginIcon(p.manifest?.frontend?.icon),
        })),
    [plugins, feedBase, t],
  );

  function isActive(to: string | null): boolean {
    if (!to) return false;
    if (to === '/') return location.pathname === '/';
    return location.pathname.startsWith(to);
  }

  const feedScoped: Array<{ to: string | null; label: string; icon: ComponentType<{ size?: number }> }> = [
    { to: feedBase ? `${feedBase}/setup` : null, label: t('nav.setup'), icon: IconSettings },
    ...(feedBase ? pluginNavItems : []),
    { to: feedBase ? `${feedBase}/products` : null, label: t('nav.products'), icon: IconBox },
    { to: feedBase ? `${feedBase}/pipeline` : null, label: t('nav.pipeline'), icon: IconGitBranch },
    { to: feedBase ? `${feedBase}/monitoring` : null, label: t('nav.monitoring'), icon: IconActivity },
    { to: feedBase ? `${feedBase}/export` : null, label: t('nav.export'), icon: IconFileExport },
  ];

  return (
    <MantineAppShell
      padding="md"
      header={{ height: 60 }}
      navbar={{ width: 260, breakpoint: 'sm', collapsed: { mobile: !opened } }}
    >
      <MantineAppShell.Header>
        <Group h="100%" px="md" justify="space-between" wrap="nowrap">
          <Group gap="md" wrap="nowrap">
            <Burger opened={opened} onClick={toggle} hiddenFrom="sm" size="sm" />
            <Title order={4}>{t('appName')}</Title>
            <FeedBreadcrumb />
          </Group>
          <Group gap="sm" wrap="nowrap">
            <LanguageSwitcher />
            <ColorSchemeToggle />
            <UserMenu />
          </Group>
        </Group>
      </MantineAppShell.Header>

      <MantineAppShell.Navbar p="md">
        <Stack gap={4}>
          <NavLink
            component={Link}
            to="/"
            label={t('nav.dashboard')}
            leftSection={<IconDashboard size={16} />}
            active={isActive('/')}
            variant={isActive('/') ? 'light' : undefined}
            color={isActive('/') ? 'blue' : undefined}
            onClick={close}
          />
          {feedScoped.map((item) =>
            item.to ? (
              <NavLink
                key={item.label}
                component={Link}
                to={item.to}
                label={item.label}
                leftSection={<item.icon size={16} />}
                active={isActive(item.to)}
                variant={isActive(item.to) ? 'light' : undefined}
                color={isActive(item.to) ? 'blue' : undefined}
                onClick={close}
              />
            ) : (
              <NavLink
                key={item.label}
                label={item.label}
                leftSection={<item.icon size={16} />}
                disabled
              />
            ),
          )}
        </Stack>
      </MantineAppShell.Navbar>

      <MantineAppShell.Main>
        <Outlet />
      </MantineAppShell.Main>
    </MantineAppShell>
  );
}
