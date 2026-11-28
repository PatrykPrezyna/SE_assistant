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
  
  function togglePanel() {
    isOpen = !isOpen;
    $panel.classList.toggle("open", isOpen);
    $toggle.textContent = isOpen ? "Close Chat" : "Chat";
    if (isOpen && $input && !isLoading) {
      setTimeout(() => $input.focus(), 350);
    }
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
    
    messages.forEach(msg => {
      const $msg = document.createElement("div");
      $msg.className = `assistant-message ${msg.role}`;
      $msg.textContent = msg.content;
      $messages.appendChild($msg);
    });
    
    if (isLoading) {
      const $loading = document.createElement("div");
      $loading.className = "assistant-loading";
      $loading.textContent = "Assistant is thinking...";
      $messages.appendChild($loading);
    }
    
    $messages.scrollTop = $messages.scrollHeight;
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
    $msg.textContent = text;
    $messages.appendChild($msg);
    $messages.scrollTop = $messages.scrollHeight;
  }
  
  async function sendMessage() {
    if (isLoading || !isConfigured) return;
    
    const text = $input.value.trim();
    if (!text) return;
    
    messages.push({ role: "user", content: text });
    $input.value = "";
    isLoading = true;
    updateInputState();
    renderMessages();
    
    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ messages })
      });
      
      const data = await res.json();
      
      if (data.error) {
        showError(data.error);
      } else {
        messages = data.messages || messages;
        renderMessages();
        
        if (data.notes && data.notes.length > 0) {
          data.notes.forEach(note => showNote(note));
        }
        
        // If assistant wrote model files, trigger a diagram refresh
        if (data.notes && data.notes.some(n => n.includes("model"))) {
          setTimeout(() => {
            if (window.refreshModel) {
              window.refreshModel();
            }
          }, 500);
        }
      }
    } catch (err) {
      showError("Network error: " + err.message);
    } finally {
      isLoading = false;
      updateInputState();
      if (!isLoading) {
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
    }
  }
  
  async function initSession() {
    try {
      const res = await fetch("/api/session");
      const data = await res.json();
      
      messages = data.messages || [];
      isConfigured = data.configured !== false;
      configMessage = data.configMessage || "";
      
      renderMessages();
      updateInputState();
    } catch (err) {
      console.error("Failed to load assistant session:", err);
      isConfigured = false;
      configMessage = "Failed to connect to assistant.";
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
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
      }
    });
  }
  
  // Initialize
  initSession();
})();
