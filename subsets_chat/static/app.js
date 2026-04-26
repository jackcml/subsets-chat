const state = {
  users: [],
  sets: new Map(),
  feeds: new Map(),
  sockets: new Map(),
  replyTo: null,
};

const els = {
  status: document.querySelector("#status"),
  createUserForm: document.querySelector("#create-user-form"),
  displayName: document.querySelector("#display-name"),
  authorSelect: document.querySelector("#author-select"),
  composeForm: document.querySelector("#compose-form"),
  messageBody: document.querySelector("#message-body"),
  replyContext: document.querySelector("#reply-context"),
  clearReply: document.querySelector("#clear-reply"),
  seedDemo: document.querySelector("#seed-demo"),
  sets: document.querySelector("#sets"),
  feeds: document.querySelector("#feeds"),
  refresh: document.querySelector("#refresh"),
};

function setStatus(text, kind = "") {
  els.status.textContent = text;
  els.status.className = `status ${kind}`.trim();
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = body.detail || detail;
    } catch {
      // Keep the response status text.
    }
    throw new Error(Array.isArray(detail) ? detail[0]?.msg || response.statusText : detail);
  }
  return response.json();
}

function userName(userId) {
  return state.users.find((user) => user.id === userId)?.display_name || `User ${userId}`;
}

function formatTime(timestamp) {
  return new Date(timestamp).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  });
}

async function loadUsers() {
  state.users = await api("/users");
  for (const user of state.users) {
    const followSet = await api(`/users/${user.id}/set`);
    state.sets.set(
      user.id,
      new Set(followSet.map((followedUser) => followedUser.id)),
    );
  }
}

async function loadFeeds() {
  await Promise.all(
    state.users.map(async (user) => {
      state.feeds.set(user.id, await api(`/feed?viewer_id=${user.id}`));
    }),
  );
}

function renderAuthorSelect() {
  els.authorSelect.innerHTML = "";
  for (const user of state.users) {
    const option = document.createElement("option");
    option.value = user.id;
    option.textContent = user.display_name;
    els.authorSelect.append(option);
  }
}

function renderSets() {
  els.sets.innerHTML = "";
  if (state.users.length === 0) {
    els.sets.innerHTML = `<div class="empty">Add or seed users to edit sets.</div>`;
    return;
  }

  for (const viewer of state.users) {
    const card = document.createElement("article");
    card.className = "set-card";
    const followedIds = state.sets.get(viewer.id) || new Set();
    card.innerHTML = `
      <header>
        <h3>${viewer.display_name}</h3>
        <span class="feed-meta">${followedIds.size} followed</span>
      </header>
      <div class="set-options"></div>
    `;

    const options = card.querySelector(".set-options");
    for (const candidate of state.users) {
      const row = document.createElement("label");
      row.className = "check-row";
      row.innerHTML = `
        <input type="checkbox" ${followedIds.has(candidate.id) ? "checked" : ""} />
        <span>${candidate.display_name}${candidate.id === viewer.id ? " (self optional)" : ""}</span>
      `;
      row.querySelector("input").addEventListener("change", async (event) => {
        const nextSet = new Set(state.sets.get(viewer.id) || []);
        if (event.target.checked) {
          nextSet.add(candidate.id);
        } else {
          nextSet.delete(candidate.id);
        }
        await api(`/users/${viewer.id}/set`, {
          method: "PUT",
          body: JSON.stringify({ followed_user_ids: [...nextSet] }),
        });
        await refreshAll(`Updated ${viewer.display_name}'s set`);
      });
      options.append(row);
    }

    els.sets.append(card);
  }
}

function renderFeeds() {
  els.feeds.innerHTML = "";
  if (state.users.length === 0) {
    els.feeds.innerHTML = `<div class="empty">No users yet. Seed a demo to start testing.</div>`;
    return;
  }

  for (const viewer of state.users) {
    const messages = state.feeds.get(viewer.id) || [];
    const followedIds = state.sets.get(viewer.id) || new Set();
    const column = document.createElement("article");
    column.className = "feed-column";
    column.innerHTML = `
      <header>
        <div>
          <h3>${viewer.display_name}'s feed</h3>
          <div class="feed-meta">sees self + ${followedIds.size} followed</div>
        </div>
        <span class="feed-meta">${messages.length} messages</span>
      </header>
      <div class="messages"></div>
    `;

    const list = column.querySelector(".messages");
    if (messages.length === 0) {
      list.innerHTML = `<div class="empty">Nothing visible from this perspective.</div>`;
    }

    for (const message of messages) {
      list.append(renderMessage(viewer, message));
    }

    els.feeds.append(column);
  }
}

function renderMessage(viewer, message) {
  const item = document.createElement("article");
  item.className = `message ${message.author_user_id === viewer.id ? "is-own" : ""}`.trim();

  const replyContext = message.reply_to
    ? `<div class="reply-context">Reply to ${message.reply_to.author_display_name}: ${escapeHtml(message.reply_to.body)}</div>`
    : "";

  item.innerHTML = `
    <div class="message-head">
      <span class="author">${message.author_display_name}</span>
      <span>${formatTime(message.created_at)}</span>
    </div>
    ${replyContext}
    <p class="body">${escapeHtml(message.body)}</p>
    <div class="message-actions">
      <button type="button">Reply</button>
    </div>
  `;

  item.querySelector("button").addEventListener("click", () => {
    state.replyTo = message;
    els.replyContext.value = `#${message.id} ${message.author_display_name}: ${message.body}`;
    els.messageBody.focus();
  });

  return item;
}

function escapeHtml(value) {
  return value.replace(/[&<>"']/g, (char) => {
    const entities = {
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#039;",
    };
    return entities[char];
  });
}

function connectSockets() {
  for (const socket of state.sockets.values()) {
    socket.onclose = null;
    socket.close();
  }
  state.sockets.clear();

  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  for (const user of state.users) {
    const socket = new WebSocket(`${protocol}://${window.location.host}/ws?viewer_id=${user.id}`);
    socket.onmessage = async () => {
      await refreshAll(`Live update for ${user.display_name}`, false);
    };
    socket.onopen = () => setStatus("Live", "ok");
    socket.onclose = () => setStatus("Socket closed", "error");
    state.sockets.set(user.id, socket);
  }
}

async function refreshAll(statusText = "Loaded", reconnect = true) {
  try {
    setStatus("Loading");
    await loadUsers();
    renderAuthorSelect();
    await loadFeeds();
    renderSets();
    renderFeeds();
    if (reconnect) {
      connectSockets();
    }
    setStatus(statusText, "ok");
  } catch (error) {
    setStatus(error.message, "error");
  }
}

async function seedDemo() {
  const existingNames = new Set(state.users.map((user) => user.display_name.toLowerCase()));
  for (const name of ["Alice", "Bob", "Charlie"]) {
    if (!existingNames.has(name.toLowerCase())) {
      await api("/users", {
        method: "POST",
        body: JSON.stringify({ display_name: name }),
      });
    }
  }
  await refreshAll("Demo users ready");
}

els.createUserForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const displayName = els.displayName.value.trim();
  if (!displayName) return;
  await api("/users", {
    method: "POST",
    body: JSON.stringify({ display_name: displayName }),
  });
  els.displayName.value = "";
  await refreshAll(`Added ${displayName}`);
});

els.composeForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const authorUserId = Number(els.authorSelect.value);
  const body = els.messageBody.value.trim();
  if (!authorUserId || !body) return;

  await api("/messages", {
    method: "POST",
    body: JSON.stringify({
      author_user_id: authorUserId,
      body,
      reply_to_message_id: state.replyTo?.id ?? null,
    }),
  });
  els.messageBody.value = "";
  state.replyTo = null;
  els.replyContext.value = "Broadcast";
  await refreshAll(`Sent as ${userName(authorUserId)}`, false);
});

els.clearReply.addEventListener("click", () => {
  state.replyTo = null;
  els.replyContext.value = "Broadcast";
});

els.seedDemo.addEventListener("click", seedDemo);
els.refresh.addEventListener("click", () => refreshAll("Refreshed", false));

refreshAll();
