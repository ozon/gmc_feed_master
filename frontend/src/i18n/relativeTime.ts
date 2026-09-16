import dayjs from 'dayjs';
import localizedFormat from 'dayjs/plugin/localizedFormat';
import relativeTime from 'dayjs/plugin/relativeTime';

let registered = false;

export function registerRelativeTime(): void {
  if (registered) return;
  dayjs.extend(relativeTime);
  dayjs.extend(localizedFormat);
  registered = true;
}
