export function usageDateParams(from: Date | null, to: Date | null): { from?: string; to?: string } {
  return {
    from: from ? new Date(from.getFullYear(), from.getMonth(), from.getDate()).toISOString() : undefined,
    to: to ? new Date(to.getFullYear(), to.getMonth(), to.getDate(), 23, 59, 59).toISOString() : undefined,
  };
}
