/* SE Assistant Chat Panel */
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
  
  // Simple markdown renderer (supports common constructs)
  function renderMarkdown(text) {
    if (!text) return "";
    
    // Escape HTML first
    text = text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    
    // Code blocks (```code```)
    text = text.replace(/```([^`]+)```/g, '<pre><code>$1</code></pre>');
    
    // Inline code (`code`)
    text = text.replace(/`([^`]+)`/g, '<code>$1</code>');
    
    // Bold (**text** or __text__)
    text = text.replace(/\*\*([^\*]+)\*\*/g, '<strong>$1</strong>');
    text = text.replace(/__([^_]+)__/g, '<strong>$1</strong>');
    
    // Italic (*text* or _text_)
    text = text.replace(/\*([^\*]+)\*/g, '<em>$1</em>');
    text = text.replace(/_([^_]+)_/g, '<em>$1</em>');
    
    // Links [text](url)
    text = text.replace(/\[([^\]]+)\]\(([^\)]+)\)/g, '<a href="$2" target="_blank">$1</a>');
    
    // Line breaks
    text = text.replace(/\n\n/g, '</p><p>');
    text = text.replace(/\n/g, '<br>');
    
    // Wrap in paragraph if not already wrapped
    if (!text.startsWith('<pre>') && !text.startsWith('<p>')) {
      text = '<p>' + text + '</p>';
    }
    
    return text;
  }
  
  function togglePanel() {
    isOpen = !isOpen;
    $panel.classList.toggle("open", isOpen);
    $toggle.textContent = isOpen ? "Close Chat" : "Chat";
    if (isOpen) {
      if (messages.length === 0 && isConfigured) {
        renderEmptyState();
      }
      if ($input && !isLoading) {
        setTimeout(() => $input.focus(), 350);
      }
    }
  }
  
  function renderEmptyState() {
    if (messages.length > 0 || !isConfigured) return;
    
    const $empty = document.createElement("div");
    $empty.className = "assistant-empty-state";
    $empty.innerHTML = `
      <h4>Welcome to SE Assistant</h4>
      <p>I can help you model your system. Try asking me to:</p>
      <div class="examples">
        <div class="example-prompt" data-prompt="Add a stakeholder">📋 Add a stakeholder</div>
        <div class="example-prompt" data-prompt="Add a use case">🎯 Add a use case</div>
        <div class="example-prompt" data-prompt="Add a nurse to the context">👤 Add a nurse to the context</div>
        <div class="example-prompt" data-prompt="What requirements do I have?">❓ What requirements do I have?</div>
      </div>
    `;
    
    $messages.innerHTML = "";
    $messages.appendChild($empty);
    
    // Add click handlers for example prompts
    $empty.querySelectorAll(".example-prompt").forEach($ex => {
      $ex.addEventListener("click", () => {
        const prompt = $ex.dataset.prompt;
        if ($input) {
          $input.value = prompt;
          $input.focus();
        }
      });
    });
  }
  
  function renderMessages() {
    $messages.innerHTML = "";
    
    if (!isConfigured) {
      const $disabled = document.createElement("div");
      $disabled.className = "assistant-disabled";
      $disabled.innerHTML = `<strong>Assistant not configured</strong>${configMessage}`;
      $messages.appendChild($disabled);
      return;
    }
    
    if (messages.length === 0) {
      renderEmptyState();
      return;
    }
    
    messages.forEach(msg => {
      const $msg = document.createElement("div");
      $msg.className = `assistant-message ${msg.role}`;
      
      if (msg.role === "assistant") {
        $msg.innerHTML = renderMarkdown(msg.content);
      } else {
        $msg.textContent = msg.content;
      }
      
      $messages.appendChild($msg);
    });
    
    if (isLoading) {
      const $loading = document.createElement("div");
      $loading.className = "assistant-loading";
      $loading.textContent = "Thinking...";
      $messages.appendChild($loading);
    }
    
    // Auto-scroll to bottom
    setTimeout(() => {
      $messages.scrollTop = $messages.scrollHeight;
    }, 10);
  }
  
  function showError(text) {
    const $msg = document.createElement("div");
    $msg.className = "assistant-message error";
    $msg.textContent = text;
    $messages.appendChild($msg);
    $messages.scrollTop = $messages.scrollHeight;
  }
  
  function showNote(text) {
    const $msg = document.createElement("div");
    $msg.className = "assistant-message note";
    $msg.innerHTML = renderMarkdown(text);
    $messages.appendChild($msg);
    $messages.scrollTop = $messages.scrollHeight;
  }
  
  async function sendMessage() {
    if (isLoading || !isConfigured) return;
    
    const text = $input.value.trim();
    if (!text) return;
    
    // Add user message immediately
    messages.push({ role: "user", content: text });
    $input.value = "";
    isLoading = true;
    updateInputState();
    renderMessages();
    
    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ messages }),
        credentials: 'same-origin'  // Send session cookie in hosted mode
      });
      
      if (!res.ok) {
        const errorText = await res.text();
        let errorMessage = `Error ${res.status}: ${res.statusText}`;
        try {
          const errorData = JSON.parse(errorText);
          errorMessage = errorData.error || errorMessage;
        } catch (e) {
          // Keep default error message
        }
        showError(errorMessage);
        return;
      }
      
      const data = await res.json();
      
      if (data.error) {
        showError(data.error);
      } else {
        // Update messages from response
        messages = data.messages || messages;
        renderMessages();
        
        // Show any notes
        if (data.notes && data.notes.length > 0) {
          data.notes.forEach(note => showNote(note));
        }
        
        // If assistant wrote model files, trigger a diagram refresh
        if (data.notes && data.notes.some(n => n.toLowerCase().includes("model") || n.toLowerCase().includes("sysml"))) {
          setTimeout(() => {
            if (typeof loadModel === "function") {
              console.log("Reloading model after assistant update...");
              loadModel();
            }
          }, 500);
        }
      }
    } catch (err) {
      console.error("Chat error:", err);
      showError("Network error: " + err.message);
    } finally {
      isLoading = false;
      updateInputState();
      if (!isLoading && $input) {
        $input.focus();
      }
    }
  }
  
  function updateInputState() {
    if ($send) {
      $send.disabled = isLoading || !isConfigured;
    }
    if ($input) {
      $input.disabled = isLoading || !isConfigured;
      $input.placeholder = isLoading ? "Assistant is thinking..." : "Ask the assistant...";
    }
  }
  
  async function initSession() {
    try {
      const res = await fetch("/api/session", {
        credentials: 'same-origin'  // Send session cookie in hosted mode
      });
      
      if (!res.ok) {
        if (res.status === 401) {
          isConfigured = false;
          configMessage = " Please sign in or configure authentication.";
        } else if (res.status === 503) {
          isConfigured = false;
          configMessage = " Assistant module not available.";
        } else {
          isConfigured = false;
          configMessage = ` Server error: ${res.status}`;
        }
        renderMessages();
        updateInputState();
        return;
      }
      
      const data = await res.json();
      
      messages = data.messages || [];
      isConfigured = data.configured !== false;
      configMessage = data.configMessage || "";
      
      if (!isConfigured && !configMessage) {
        configMessage = " Set ASSISTANT_BASE_URL and ASSISTANT_MODEL environment variables.";
      }
      
      renderMessages();
      updateInputState();
    } catch (err) {
      console.error("Failed to load assistant session:", err);
      isConfigured = false;
      configMessage = " Failed to connect to assistant.";
      renderMessages();
      updateInputState();
    }
  }
  
  // Event listeners
  $toggle.addEventListener("click", togglePanel);
  $close.addEventListener("click", togglePanel);
  
  if ($send) {
    $send.addEventListener("click", sendMessage);
  }
  
  if ($input) {
    $input.addEventListener("keydown", (e) => {
      // Enter sends message, Shift+Enter adds newline
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
      }
    });
    
    // Auto-resize textarea as user types
    $input.addEventListener("input", () => {
      $input.style.height = "auto";
      $input.style.height = Math.min($input.scrollHeight, 120) + "px";
    });
  }
  
  // Initialize
  initSession();
})();
