import { normalizeId, parseFeed, shardOf, subscribeLinks, svaraFeedId } from "./logic.js";

const base = new URL(".", location.href);
const $ = (id) => document.getElementById(id);
const statusLine = $("status");
const result = $("result");
const shards = new Map();
const upcomingShown = 4;
const formatDate = new Intl.DateTimeFormat("lt-LT", {
  weekday: "long",
  month: "long",
  day: "numeric",
  timeZone: "UTC",
});

class NotFound extends Error {}

function localToday() {
  return new Date().toLocaleDateString("sv-SE");
}

function setStatus(message, isError = false) {
  statusLine.textContent = message;
  statusLine.classList.toggle("error", isError);
}

async function fetchOk(path) {
  const response = await fetch(new URL(path, base));
  if (response.status === 404) throw new NotFound(path);
  if (!response.ok) throw new Error(`${path}: HTTP ${response.status}`);
  return response;
}

async function lookupFeed(rawId) {
  const id = normalizeId(rawId);
  const shard = await shardOf(id);
  if (!shards.has(shard)) {
    shards.set(
      shard,
      fetchOk(`lookup/${shard}.json`)
        .then((response) => response.json())
        .catch((error) => {
          shards.delete(shard);
          if (error instanceof NotFound) return {};
          throw error;
        }),
    );
  }
  const feedId = (await shards.get(shard))[id];
  if (!feedId) throw new NotFound(id);
  return feedId;
}

async function showFeed(feedId) {
  const path = `feeds/${feedId}.ics`;
  const feed = parseFeed(await (await fetchOk(path)).text());
  const today = localToday();
  const upcoming = feed.dates.filter((date) => date >= today).slice(0, upcomingShown);

  $("result-name").textContent = feed.name;
  $("result-details").textContent = feed.details;
  const list = $("result-dates");
  list.replaceChildren(
    ...(upcoming.length
      ? upcoming.map((date) => {
          const item = document.createElement("li");
          item.textContent = formatDate.format(new Date(`${date}T00:00:00Z`));
          return item;
        })
      : [Object.assign(document.createElement("li"), { textContent: "Artimiausiu metu išvežimų nesuplanuota." })]),
  );

  const links = subscribeLinks(new URL(path, base).href, feed.name);
  $("add-google").href = links.google;
  $("add-apple").href = links.apple;
  $("add-outlook").href = links.outlook;
  $("copy-link").dataset.url = links.https;

  result.hidden = false;
  result.scrollIntoView({ behavior: "smooth", block: "start" });
}

async function run(task) {
  setStatus("Ieškoma…");
  result.hidden = true;
  try {
    await task();
    setStatus("");
  } catch (error) {
    if (!(error instanceof NotFound)) console.error(error);
    setStatus(
      error instanceof NotFound
        ? "Tokio konteinerio neradome. Patikrinkite numerį (pavyzdžiui, 52-S-00000). " +
            "Jei jūsų konteinerį aptarnauja Svara, rinkitės skirtuką „Svara“."
        : "Nepavyko įkelti duomenų. Patikrinkite interneto ryšį ir bandykite dar kartą.",
      true,
    );
  }
}

$("panel-ekonovus").addEventListener("submit", (event) => {
  event.preventDefault();
  const raw = $("container").value;
  if (!normalizeId(raw)) return;
  run(async () => showFeed(await lookupFeed(raw)));
});

$("panel-svara").addEventListener("submit", (event) => {
  event.preventDefault();
  const date = $("svara-date").value;
  if (!date) return;
  run(() => showFeed(svaraFeedId(date, Number($("svara-interval").value))));
});

$("copy-link").addEventListener("click", async (event) => {
  const url = event.currentTarget.dataset.url;
  try {
    await navigator.clipboard.writeText(url);
    setStatus("Nuoroda nukopijuota. Įklijuokite ją savo kalendoriaus programoje.");
  } catch {
    window.prompt("Nukopijuokite šią nuorodą:", url);
  }
});

const tabs = ["ekonovus", "svara"];
function selectTab(name) {
  for (const tab of tabs) {
    const selected = tab === name;
    const button = $(`tab-${tab}`);
    button.setAttribute("aria-selected", String(selected));
    button.tabIndex = selected ? 0 : -1;
    $(`panel-${tab}`).hidden = !selected;
  }
  result.hidden = true;
  setStatus("");
}
for (const tab of tabs) {
  $(`tab-${tab}`).addEventListener("click", () => selectTab(tab));
  $(`tab-${tab}`).addEventListener("keydown", (event) => {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    const next = tabs[(tabs.indexOf(tab) + 1) % tabs.length];
    selectTab(next);
    $(`tab-${next}`).focus();
  });
}

$("svara-date").min = localToday();
