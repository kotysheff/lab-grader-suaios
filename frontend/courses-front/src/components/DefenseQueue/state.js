export const identityKey = (course, group) => `queue.identity.${JSON.stringify([course, group])}`;
export function cleanIdentity(value = {}) {
  return Object.fromEntries(["surname", "name", "patronymic", "github"].map(key => [key, typeof value?.[key] === "string" ? value[key] : ""]));
}
export const canIdentify = identity => Boolean(identity?.surname?.trim() && identity?.name?.trim() && identity?.github?.trim());
export const ownEntry = (entries, github) => entries?.find(row => row.github?.toLowerCase() === github?.trim().toLowerCase());
export function entryLabel(row, { current, next } = {}) {
  if (current != null && (Array.isArray(current) ? current.includes(row.attempt?.entry_id) : row.attempt?.entry_id === current)) return "Сдаёт сейчас";
  if (next != null && row.attempt?.entry_id === next) return row.attempt.is_repeat ? "Следующий · повторно" : "Следующий";
  const states = { waiting: "Ожидает", called: "Вызван", defended: "Защитил", failed: "Не защитил", no_show: "Не явился", withdrawn: "Исключён", expired: "Занятие завершено" };
  if (row.attempt) return `${states[row.attempt.status] || row.attempt.status}${row.attempt.is_repeat ? " · повторно" : ""}`;
  return ({ attending: "Придёт", declined: "Не придёт", unconfirmed: "Не подтверждено" })[row.state] || "Не подтверждено";
}
export function displayDate(timestamp, zone = "Europe/Moscow", locale = "ru-RU") {
  if (!timestamp) return "Дата не назначена";
  return new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeStyle: "short", timeZone: zone }).format(new Date(timestamp * 1000));
}
