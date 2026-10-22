import assert from "node:assert/strict";
import { test } from "node:test";

import {
  normalizeId,
  parseFeed,
  shardOf,
  subscribeLinks,
  svaraFeedId,
} from "../../site/logic.js";

// The same vectors are asserted in tests/test_feeds.py against trash_feeds/feeds.py.
const ids = [
  ["99-S-00001", "99-S-00001", "ec"],
  [" 99–ž-00042 ", "99-Ž-00042", "6f"],
  ["12-KAP001", "12-KAP001", "a3"],
];

test("normalizeId and shardOf match the generator", async () => {
  for (const [raw, normalized, shard] of ids) {
    assert.equal(normalizeId(raw), normalized);
    assert.equal(await shardOf(normalized), shard);
  }
});

test("svaraFeedId matches the generator", () => {
  assert.equal(svaraFeedId("2026-10-28", 2), "svara-2w-d2-p1");
  assert.equal(svaraFeedId("2026-11-04", 2), "svara-2w-d2-p0");
  assert.equal(svaraFeedId("2023-12-31", 3), "svara-3w-d6-p2");
  assert.equal(svaraFeedId("2026-10-26", 1), "svara-1w-d0-p0");
  assert.equal(svaraFeedId("2027-01-15", 4), "svara-4w-d4-p2");
});

test("parseFeed reads the name, details and dates of a folded feed", () => {
  const ics = [
    "BEGIN:VCALENDAR",
    "X-WR-CALNAME:Šiukšlės: stiklas (Ekonovus)",
    "BEGIN:VEVENT",
    "DTSTART;VALUE=DATE:20261112",
    "DESCRIPTION:Ekonovus · kas 14 dienų\\n\\nGrafikas atnaujinamas kasdien: https:",
    " //example.github.io/trash",
    "END:VEVENT",
    "BEGIN:VEVENT",
    "DTSTART;VALUE=DATE:20261029",
    "END:VEVENT",
    "END:VCALENDAR",
  ].join("\r\n");

  assert.deepEqual(parseFeed(ics), {
    name: "Šiukšlės: stiklas (Ekonovus)",
    details: "Ekonovus · kas 14 dienų",
    dates: ["2026-10-29", "2026-11-12"],
  });
});

test("subscribeLinks builds per-app links", () => {
  const links = subscribeLinks("https://example.github.io/trash/feeds/abc.ics", "Šiukšlės");
  assert.equal(links.apple, "webcal://example.github.io/trash/feeds/abc.ics");
  assert.equal(
    links.google,
    "https://calendar.google.com/calendar/render?cid=webcal%3A%2F%2Fexample.github.io%2Ftrash%2Ffeeds%2Fabc.ics",
  );
  assert.ok(links.outlook.startsWith("https://outlook.live.com/calendar/0/addfromweb?url=https%3A"));
  assert.ok(links.outlook.endsWith("&name=%C5%A0iuk%C5%A1l%C4%97s"));
});
