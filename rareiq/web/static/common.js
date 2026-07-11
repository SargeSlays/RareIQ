function connectRareIQ(onMessage) {
  const protocol = location.protocol === "https:" ? "wss" : "ws";
  let socket;

  function connect() {
    socket = new WebSocket(`${protocol}://${location.host}/ws`);
    socket.onmessage = event => {
      try { onMessage(JSON.parse(event.data)); }
      catch (error) { console.error(error); }
    };
    socket.onclose = () => setTimeout(connect, 800);
    socket.onerror = () => socket.close();
  }

  connect();
}

function money(value) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD"
  }).format(value || 0);
}
