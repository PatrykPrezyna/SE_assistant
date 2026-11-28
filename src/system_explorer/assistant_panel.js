/* SE Assistant chat panel. Same-origin fetch sends the session cookie
   by default; nothing extra is required for hosted sign-in. */
(function() {
  "use strict";

  let messages = [];
  let isOpen = false;
  let isConfigured = true;
  let configMessage = "";
  let isLoading = false;

  const $panel = document.getElementById("assistantPanel");
  const $toggle = document.getElementById("assistantToggle");
  const $close = document.getElementById("assistantClose");
  const $messages = document.getElementById("assistantMessages");
  const $input = document.getElementById("assistantInputText");
  const $send = document.getElementById("assistantSend");

  const SUGGESTIONS = [
    "Add a nurse to the context",
    "What is in the context view?",
    "Which requirements are still open?"
  ];

  function renderMarkdown(text) {
    if (!text) return "";
    text = text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    text = text.replace(/```([^`]+)```/g, "<pre><code>$1</code></pre>");
    text = text.replace(/`([^`]+)`/g, "<code>$1</code>");
    text = text.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    text = text.replace(/__([^_]+)__/g, "<strong>$1</strong>");
    text = text.replace(/\*([^*]+)\*/g, "<em>$1</em>");
    text = text.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
    text = text.replace(/\n\n/g, "</p><p>");
    text = text.replace(/\n/g, "<br>");
    if (!text.startsWith("<pre>") && !text.startsWith("<p>")) {
      text = "<p>" + text + "</p>";
    }
    return text;
  }

  function transcriptForServer() {
    return messages
      .filter(msg => msg.role === "user" || msg.role === "assistant")
      .map(msg => ({ role: msg.role, content: msg.content }));
  }

  function togglePanel() {
    isOpen = !isOpen;
    $panel.classList.toggle("open", isOpen);
    document.body.classList.toggle("assistant-open", isOpen);
    $toggle.textContent = isOpen ? "Close" : "Chat";
    $toggle.setAttribute("aria-expanded", isOpen ? "true" : "false");
    if (isOpen && $input && !isLoading && isConfigured) {
      setTimeout(() => $input.focus(), 280);
    }
  }

  function showSuggestions() {
    const onlyGreeting = messages.length === 1 && messages[0].role === "assistant";
    if (!onlyGreeting || isLoading) return;
    const $row = document.createElement("div");
    $row.className = "assistant-suggestions";
    for (const prompt of SUGGESTIONS) {
      const $btn = document.createElement("button");
      $btn.type = "button";
      $btn.className = "assistant-suggestion";
      $btn.textContent = prompt;
      $btn.addEventListener("click", () => sendMessage(prompt));
      $row.appendChild($btn);
    }
    $messages.appendChild($row);
  }

  function renderMessages() {
    $messages.innerHTML = "";

    if (!isConfigured) {
      const $disabled = document.createElement("div");
      $disabled.className = "assistant-disabled";
      $disabled.innerHTML = "<strong>Assistant unavailable</strong><p></p>";
      $disabled.querySelector("p").textContent = configMessage ||
        "Set ASSISTANT_BASE_URL and ASSISTANT_MODEL, then restart the explorer.";
      $messages.appendChild($disabled);
      return;
    }

    if (!messages.length) {
      const $empty = document.createElement("div");
      $empty.className = "assistant-empty-state";
      $empty.innerHTML = "<h4>Ask about this model</h4><p>Add a person, check a requirement, or ask what is already in the diagram.</p>";
      $messages.appendChild($empty);
      return;
    }

    messages.forEach(msg => {
      const $msg = document.createElement("div");
      $msg.className = "assistant-message " + msg.role;
      if (msg.role === "assistant" || msg.role === "note") {
        $msg.innerHTML = renderMarkdown(msg.content);
      } else {
        $msg.textContent = msg.content;
      }
      $messages.appendChild($msg);
    });

    showSuggestions();

    if (isLoading) {
      const $loading = document.createElement("div");
      $loading.className = "assistant-loading";
      $loading.textContent = "Thinking";
      $messages.appendChild($loading);
    }

    $messages.scrollTop = $messages.scrollHeight;
  }

  function updateInputState() {
    const locked = isLoading || !isConfigured;
    if ($send) $send.disabled = locked;
    if ($input) {
      $input.disabled = locked;
      $input.placeholder = isLoading ? "Assistant is thinking…" : "Ask about the model";
    }
  }

  async function sendMessage(textOverride) {
    if (isLoading || !isConfigured) return;
    const text = (textOverride != null ? String(textOverride) : $input.value).trim();
    if (!text) return;

    messages.push({ role: "user", content: text });
    if ($input) {
      $input.value = "";
      $input.style.height = "auto";
    }
    isLoading = true;
    updateInputState();
    renderMessages();

    let changed = false;
    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ messages: transcriptForServer() })
      });
      const raw = await res.text();
      let data = null;
      try { data = JSON.parse(raw); } catch (err) { data = null; }

      if (!res.ok || !data) {
        const message = (data && data.error) ||
          ("The assistant could not reply (" + res.status + ").");
        messages.push({ role: "error", content: message });
      } else if (data.error) {
        messages.push({ role: "error", content: data.error });
      } else {
        const notes = data.notes || [];
        messages = data.messages || messages;
        notes.forEach(note => messages.push({ role: "note", content: note }));
        changed = notes.some(note => /model|sysml/i.test(note));
      }
    } catch (err) {
      messages.push({ role: "error", content: "Network error: " + (err.message || "request failed") });
    } finally {
      // Clear the thinking state before drawing, or the spinner stays
      // under the reply forever.
      isLoading = false;
      updateInputState();
      renderMessages();
      if ($input && isConfigured) $input.focus();
    }

    if (changed && typeof refreshAfterAssistantEdit === "function") {
      try {
        await refreshAfterAssistantEdit();
      } catch (err) {
        console.error("Diagram refresh failed:", err);
      }
    }
  }

  async function initSession() {
    try {
      const res = await fetch("/api/session");
      if (!res.ok) {
        isConfigured = false;
        if (res.status === 401) configMessage = "Sign in to use the assistant.";
        else if (res.status === 503) configMessage = "The assistant module is not available on this server.";
        else configMessage = "The assistant could not start (" + res.status + ").";
        renderMessages();
        updateInputState();
        return;
      }
      const data = await res.json();
      messages = data.messages || [];
      isConfigured = data.configured !== false;
      configMessage = data.configMessage || "";
      if (!isConfigured && !configMessage) {
        configMessage = "Set ASSISTANT_BASE_URL and ASSISTANT_MODEL, then restart the explorer.";
      }
      renderMessages();
      updateInputState();
    } catch (err) {
      isConfigured = false;
      configMessage = "Could not reach the assistant.";
      renderMessages();
      updateInputState();
    }
  }

  if ($toggle) $toggle.addEventListener("click", togglePanel);
  if ($close) $close.addEventListener("click", togglePanel);
  if ($send) $send.addEventListener("click", () => sendMessage());
  if ($input) {
    $input.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
      }
    });
    $input.addEventListener("input", () => {
      $input.style.height = "auto";
      $input.style.height = Math.min($input.scrollHeight, 140) + "px";
    });
  }

  initSession();
})();
