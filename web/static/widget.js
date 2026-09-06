(function () {
  "use strict";

  var API_URL = "/api/chat";
  var STORAGE_KEY = "sales-agent-user-id";

  function getUserId() {
    try {
      var id = localStorage.getItem(STORAGE_KEY);
      if (!id) {
        id = "web-" + Math.random().toString(36).slice(2, 10);
        localStorage.setItem(STORAGE_KEY, id);
      }
      return id;
    } catch (e) {
      return "web-anon";
    }
  }

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  }

  function init(rootId) {
    var root = document.getElementById(rootId || "sales-chat");
    if (!root) return;

    var box = el("div", "sa-box");
    var log = el("div", "sa-log");
    var form = el("form", "sa-form");
    var input = el("input", "sa-input");
    input.type = "text";
    input.placeholder = "Ask about pricing, features, or booking a demo…";
    input.setAttribute("aria-label", "Chat message");
    var btn = el("button", "sa-send", "Send");
    btn.type = "submit";

    form.appendChild(input);
    form.appendChild(btn);
    box.appendChild(log);
    box.appendChild(form);
    root.appendChild(box);

    var userId = getUserId();
    var busy = false;

    function addMsg(who, text) {
      var row = el("div", "sa-msg sa-" + who, text);
      log.appendChild(row);
      log.scrollTop = log.scrollHeight;
      return row;
    }

    addMsg("bot", "Hi! How can I help you today?");

    form.addEventListener("submit", function (ev) {
      ev.preventDefault();
      var text = input.value.trim();
      if (!text || busy) return;
      busy = true;
      addMsg("user", text);
      input.value = "";
      var thinking = addMsg("bot sa-thinking", "…");
      fetch(API_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id: userId, message: text }),
      })
        .then(function (r) {
          if (!r.ok) throw new Error("HTTP " + r.status);
          return r.json();
        })
        .then(function (data) {
          thinking.textContent = data.reply || "(no reply)";
        })
        .catch(function () {
          thinking.textContent = "Sorry, something went wrong. Please try again.";
        })
        .finally(function () {
          busy = false;
          input.focus();
        });
    });
  }

  window.SalesChat = { init: init };
  if (document.readyState !== "loading") init();
  else document.addEventListener("DOMContentLoaded", function () { init(); });
})();
