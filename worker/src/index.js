import { createClient } from "@tursodatabase/serverless/compat";

const HELP = `Commands:
/subscribe - start tracking alerts
/addlocation <lat> <lon> <radius_km> [label] - track a point region (earthquakes, fires)
/addcountry <code> [label] - track a country (economic, political)
/setseverity <0-5> - minimum severity to notify you
/locations - list what you're tracking
/removelocation <id> - stop tracking one
/unsubscribe - stop all alerts and delete your data
/help - show this message`;

function db(env) {
  return createClient({ url: env.TURSO_DATABASE_URL, authToken: env.TURSO_AUTH_TOKEN });
}

async function replyToTelegram(env, chatId, text) {
  await fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/sendMessage`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ chat_id: chatId, text }),
  });
}

async function ensureSubscriber(client, chatId) {
  await client.execute({
    sql: "INSERT OR IGNORE INTO subscribers (telegram_chat_id, min_severity, active, created_at) VALUES (?, 3, 1, ?)",
    args: [chatId, new Date().toISOString()],
  });
  const result = await client.execute({
    sql: "SELECT id FROM subscribers WHERE telegram_chat_id = ?",
    args: [chatId],
  });
  return result.rows[0].id;
}

async function locationCount(client, subscriberId) {
  const result = await client.execute({
    sql: "SELECT COUNT(*) as n FROM subscriber_locations WHERE subscriber_id = ?",
    args: [subscriberId],
  });
  return result.rows[0].n;
}

async function handleCommand(env, chatId, text) {
  const client = db(env);
  const [command, ...rest] = text.trim().split(/\s+/);

  switch (command) {
    case "/start":
    case "/subscribe": {
      await ensureSubscriber(client, chatId);
      return replyToTelegram(
        env, chatId,
        "Subscribed. Use /addlocation or /addcountry to pick what to track, then /help for everything else."
      );
    }

    case "/addlocation": {
      const subscriberId = await ensureSubscriber(client, chatId);
      const [latStr, lonStr, radiusStr, ...labelParts] = rest;
      const lat = parseFloat(latStr);
      const lon = parseFloat(lonStr);
      const radiusKm = parseFloat(radiusStr);
      if ([lat, lon, radiusKm].some(Number.isNaN)) {
        return replyToTelegram(env, chatId, "Usage: /addlocation <lat> <lon> <radius_km> [label]");
      }
      if ((await locationCount(client, subscriberId)) >= 5) {
        return replyToTelegram(env, chatId, "You're already tracking 5 locations, the max. Remove one with /removelocation first.");
      }
      const label = labelParts.join(" ") || `${lat},${lon}`;
      try {
        await client.execute({
          sql: `INSERT INTO subscriber_locations (subscriber_id, scope_type, label, lat, lon, radius_km, created_at)
                VALUES (?, 'point', ?, ?, ?, ?, ?)`,
          args: [subscriberId, label, lat, lon, radiusKm, new Date().toISOString()],
        });
      } catch (err) {
        return replyToTelegram(env, chatId, "Couldn't add that location -- you may already be at the 5-location limit.");
      }
      return replyToTelegram(env, chatId, `Tracking "${label}" within ${radiusKm}km.`);
    }

    case "/addcountry": {
      const subscriberId = await ensureSubscriber(client, chatId);
      const [codeRaw, ...labelParts] = rest;
      if (!codeRaw) {
        return replyToTelegram(env, chatId, "Usage: /addcountry <ISO country code> [label]");
      }
      const code = codeRaw.toUpperCase();
      if ((await locationCount(client, subscriberId)) >= 5) {
        return replyToTelegram(env, chatId, "You're already tracking 5 locations, the max. Remove one with /removelocation first.");
      }
      const label = labelParts.join(" ") || code;
      try {
        await client.execute({
          sql: `INSERT INTO subscriber_locations (subscriber_id, scope_type, label, country_code, created_at)
                VALUES (?, 'country', ?, ?, ?)`,
          args: [subscriberId, label, code, new Date().toISOString()],
        });
      } catch (err) {
        return replyToTelegram(env, chatId, "Couldn't add that country -- you may already be at the 5-location limit.");
      }
      return replyToTelegram(env, chatId, `Tracking economic/political signals for ${label} (${code}).`);
    }

    case "/setseverity": {
      const level = parseFloat(rest[0]);
      if (Number.isNaN(level) || level < 0 || level > 5) {
        return replyToTelegram(env, chatId, "Usage: /setseverity <0-5>");
      }
      await ensureSubscriber(client, chatId);
      await client.execute({
        sql: "UPDATE subscribers SET min_severity = ? WHERE telegram_chat_id = ?",
        args: [level, chatId],
      });
      return replyToTelegram(env, chatId, `Minimum severity set to ${level}.`);
    }

    case "/locations": {
      const subscriberId = await ensureSubscriber(client, chatId);
      const result = await client.execute({
        sql: "SELECT id, scope_type, label, radius_km, country_code FROM subscriber_locations WHERE subscriber_id = ?",
        args: [subscriberId],
      });
      if (result.rows.length === 0) {
        return replyToTelegram(env, chatId, "You're not tracking any locations yet. Use /addlocation or /addcountry.");
      }
      const lines = result.rows.map((r) =>
        r.scope_type === "point"
          ? `#${r.id} · ${r.label} (${r.radius_km}km radius)`
          : `#${r.id} · ${r.label} (${r.country_code})`
      );
      return replyToTelegram(env, chatId, lines.join("\n"));
    }

    case "/removelocation": {
      const id = parseInt(rest[0], 10);
      if (Number.isNaN(id)) {
        return replyToTelegram(env, chatId, "Usage: /removelocation <id> (see /locations for ids)");
      }
      const subscriberId = await ensureSubscriber(client, chatId);
      await client.execute({
        sql: "DELETE FROM subscriber_locations WHERE id = ? AND subscriber_id = ?",
        args: [id, subscriberId],
      });
      return replyToTelegram(env, chatId, `Removed location #${id} (if it was yours).`);
    }

    case "/unsubscribe": {
      await client.execute({
        sql: "DELETE FROM subscribers WHERE telegram_chat_id = ?",
        args: [chatId],
      });
      return replyToTelegram(env, chatId, "Unsubscribed, and all your tracked locations were deleted.");
    }

    case "/help":
    default:
      return replyToTelegram(env, chatId, HELP);
  }
}

export default {
  async fetch(request, env) {
    if (request.method !== "POST") {
      return new Response("ok");
    }

    // Verifies the request actually came from Telegram, not just anyone who
    // finds this Worker's URL -- set via setWebhook's secret_token param.
    const secret = request.headers.get("x-telegram-bot-api-secret-token");
    if (secret !== env.TELEGRAM_WEBHOOK_SECRET) {
      return new Response("forbidden", { status: 403 });
    }

    let update;
    try {
      update = await request.json();
    } catch (err) {
      return new Response("bad request", { status: 400 });
    }

    const message = update.message;
    if (!message || !message.text) {
      return new Response("ok");
    }

    const chatId = String(message.chat.id);

    try {
      await handleCommand(env, chatId, message.text);
    } catch (err) {
      // Never log chat_id or location data -- this Worker's logs are as
      // visible as the GitHub Actions run logs, same rule applies here.
      console.error("webhook error:", err.message);
    }

    return new Response("ok");
  },
};
