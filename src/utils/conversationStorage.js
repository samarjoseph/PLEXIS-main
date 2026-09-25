const STORAGE_PREFIX = 'plexis_conversations_';

function storageKey(userId) {
  return `${STORAGE_PREFIX}${userId || 'anonymous'}`;
}

export function loadConversations(userId) {
  try {
    const raw = localStorage.getItem(storageKey(userId));
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

export function saveConversations(userId, conversations) {
  localStorage.setItem(storageKey(userId), JSON.stringify(conversations));
}

export function createConversation({ title = 'New Chat', datasetName = null } = {}) {
  const now = Date.now();
  return {
    id: `conv_${now}_${Math.random().toString(36).slice(2, 9)}`,
    title,
    datasetName,
    pinned: false,
    messages: [
      {
        id: 'welcome',
        sender: 'ai',
        text: '# Welcome to Plexis\nUpload a dataset or ask a question to begin your analysis session.',
        hasChart: false,
      },
    ],
    chartData: { labels: [], datasets: [] },
    activeDatasetName: datasetName || 'No active dataset',
    createdAt: now,
    updatedAt: now,
  };
}

export function updateConversation(conversations, id, patch) {
  return conversations.map((c) =>
    c.id === id ? { ...c, ...patch, updatedAt: Date.now() } : c
  );
}

export function deleteConversation(conversations, id) {
  return conversations.filter((c) => c.id !== id);
}

export function renameConversation(conversations, id, title) {
  return updateConversation(conversations, id, { title });
}

export function togglePinConversation(conversations, id) {
  return conversations.map((c) =>
    c.id === id ? { ...c, pinned: !c.pinned, updatedAt: Date.now() } : c
  );
}

export function searchConversations(conversations, query) {
  const q = query.trim().toLowerCase();
  if (!q) return conversations;
  return conversations.filter(
    (c) =>
      c.title.toLowerCase().includes(q) ||
      (c.datasetName && c.datasetName.toLowerCase().includes(q))
  );
}

export function sortConversations(conversations) {
  return [...conversations].sort((a, b) => {
    if (a.pinned !== b.pinned) return a.pinned ? -1 : 1;
    return b.updatedAt - a.updatedAt;
  });
}
