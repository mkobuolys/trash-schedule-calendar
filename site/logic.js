const DAY_MS = 86_400_000;
const REFERENCE_MONDAY = Date.UTC(2024, 0, 1);

export function normalizeId(raw) {
  return raw
    .normalize("NFC")
    .replace(/\s+/g, "")
    .replace(/[‐-―−]/g, "-")
    .toUpperCase();
}

export async function shardOf(normalizedId) {
  const digest = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(normalizedId),
  );
  return new Uint8Array(digest)[0].toString(16).padStart(2, "0");
}

export function svaraFeedId(isoDate, interval) {
  const [year, month, day] = isoDate.split("-").map(Number);
  const days = Math.round((Date.UTC(year, month - 1, day) - REFERENCE_MONDAY) / DAY_MS);
  const weekday = ((days % 7) + 7) % 7;
  const phase = ((Math.floor(days / 7) % interval) + interval) % interval;
  return `svara-${interval}w-d${weekday}-p${phase}`;
}

function unescapeText(value) {
  return value.replace(/\\([\\;,nN])/g, (_, char) => (char.toLowerCase() === "n" ? "\n" : char));
}

export function parseFeed(text) {
  const unfolded = text.replace(/\r?\n[ \t]/g, "");
  const name = unfolded.match(/^X-WR-CALNAME:(.*)$/m);
  const description = unfolded.match(/^DESCRIPTION:(.*)$/m);
  const dates = [...unfolded.matchAll(/^DTSTART;VALUE=DATE:(\d{4})(\d{2})(\d{2})\s*$/gm)].map(
    ([, y, m, d]) => `${y}-${m}-${d}`,
  );
  return {
    name: name ? unescapeText(name[1].trim()) : "",
    details: description ? unescapeText(description[1].trim()).split("\n")[0] : "",
    dates: dates.sort(),
  };
}

export function subscribeLinks(feedUrl, name) {
  const webcal = feedUrl.replace(/^https?:/, "webcal:");
  return {
    google: `https://calendar.google.com/calendar/render?cid=${encodeURIComponent(webcal)}`,
    apple: webcal,
    outlook:
      "https://outlook.live.com/calendar/0/addfromweb" +
      `?url=${encodeURIComponent(feedUrl)}&name=${encodeURIComponent(name)}`,
    https: feedUrl,
  };
}
