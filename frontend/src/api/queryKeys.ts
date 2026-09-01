export const queryKeys = {
  session: ['session'] as const,
  dashboardSummary: ['dashboard', 'summary'] as const,
  clients: ['clients'] as const,
  plugins: ['plugins'] as const,
  registryAttributes: ['registry', 'attributes'] as const,
  productDetail: (feedSourceId: number | string, productId: string) =>
    ['feed-source', feedSourceId, 'products', 'detail', productId] as const,
  feedSource: (id: number | string) => ({
    detail: ['feed-source', id] as const,
    products: (params: unknown) => ['feed-source', id, 'products', params] as const,
    pipeline: ['feed-source', id, 'pipeline'] as const,
    runs: ['feed-source', id, 'runs'] as const,
    findings: ['feed-source', id, 'findings'] as const,
    exportHistory: ['feed-source', id, 'export-history'] as const,
    exportDiff: (params: { version: number; against: number } | undefined) =>
      ['feed-source', id, 'export-diff', params ?? { disabled: true }] as const,
    fieldMapping: ['feed-source', id, 'field-mapping'] as const,
    mapping: ['feed-source', id, 'field-mapping'] as const,
  }),
  pluginConfig: (pluginId: string, scope?: { clientId?: number; feedSourceId?: number }) =>
    ['plugin-config', pluginId, scope ?? {}] as const,
};
