function toggleHomeChat() {
    document.getElementById("homepage-chat-widget").classList.toggle("visible");
  }
  
  document.addEventListener("DOMContentLoaded", () => {
    const form = document.getElementById("homepage-chat-form");
    const input = document.getElementById("homepage-chat-input");
    const body = document.getElementById("homepage-chat-body");
  
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const msg = input.value.trim();
      if (!msg) return;
  
      const userBubble = document.createElement("div");
      userBubble.className = "chat-message user";
      userBubble.innerText = msg;
      body.appendChild(userBubble);
      input.value = "";
  
      const response = await fetch("/home_chat_api", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: msg })
      });
  
      const data = await response.json();
      const botBubble = document.createElement("div");
      botBubble.className = "chat-message bot";
      botBubble.innerText = data.reply || "Hmm, I'm not sure how to respond.";
      body.appendChild(botBubble);
  
      body.scrollTop = body.scrollHeight;
    });
  });
  