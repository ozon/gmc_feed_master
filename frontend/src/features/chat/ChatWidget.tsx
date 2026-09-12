import { useState } from 'react';
import {
  ActionIcon, Alert, Badge, Button, Drawer, Group, ScrollArea, Stack, Text, Textarea, Title,
} from '@mantine/core';
import { IconMessage } from '@tabler/icons-react';
import { useDisclosure } from '@mantine/hooks';
import { useTranslation } from 'react-i18next';
import { useChat, useSession } from '../../api/hooks';
import type { ChatMessage } from '../../api/types';

export function ChatWidget() {
  const { t } = useTranslation('chat');
  const { data: session } = useSession();
  const chat = useChat();
  const [opened, { open, close }] = useDisclosure(false);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');

  function send() {
    const text = input.trim();
    if (!text || chat.isPending) return;
    const conversation: ChatMessage[] = [...messages, { role: 'user', content: text }];
    setMessages(conversation);
    setInput('');
    chat.mutate(conversation, {
      onSuccess: (data) =>
        setMessages((prev) => [...prev, { role: 'assistant', content: data.content }]),
      // errors surface via chat.isError below
    });
  }

  return (
    <>
      <ActionIcon variant="subtle" aria-label={t('open')} onClick={open}>
        <IconMessage size={18} />
      </ActionIcon>
      <Drawer opened={opened} onClose={close} title={<Title order={5}>{t('title')}</Title>} position="right" size="md">
        <Stack gap="sm" h="100%">
          <Group gap="xs">
            <Badge variant="light" color={session?.role === 'admin' ? 'grape' : 'blue'}>
              {session?.role === 'admin' ? t('adminScope') : t('clientScope')}
            </Badge>
            {messages.length > 0 && (
              <Button size="compact-xs" variant="subtle" onClick={() => setMessages([])}>
                {t('clear')}
              </Button>
            )}
          </Group>
          <ScrollArea.Autosize mah="60vh">
            <Stack gap="sm">
              {messages.length === 0 && <Text size="sm" c="dimmed">{t('empty')}</Text>}
              {messages.map((m, i) => (
                <Text
                  key={i}
                  size="sm"
                  c={m.role === 'user' ? 'blue' : undefined}
                  style={{ whiteSpace: 'pre-wrap' }}
                  data-testid={`chat-message-${i}`}
                >
                  {m.content}
                </Text>
              ))}
              {chat.isPending && <Text size="sm" c="dimmed">{t('thinking')}</Text>}
              {chat.isError && (
                <Alert color="red" role="alert">{t('failed')}</Alert>
              )}
            </Stack>
          </ScrollArea.Autosize>
          <Textarea
            aria-label={t('inputLabel')}
            value={input}
            onChange={(e) => setInput(e.currentTarget.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                send();
              }
            }}
            autosize
            minRows={2}
          />
          <Button onClick={send} loading={chat.isPending}>{t('send')}</Button>
        </Stack>
      </Drawer>
    </>
  );
}
