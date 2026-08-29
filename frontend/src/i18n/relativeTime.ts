import dayjs from 'dayjs';
import relativeTime from 'dayjs/plugin/relativeTime';

let registered = false;

export function registerRelativeTime(): void {
  if (registered) return;
  dayjs.extend(relativeTime);
  registered = true;
}
