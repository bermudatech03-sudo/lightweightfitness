// Web Push service worker for GymPro CRM — handles incoming push events and
// notification clicks. Registered from src/push/pushClient.js.
// Served at /push-sw.js (Vite copies public/ files to the build root as-is).

self.addEventListener("push", (event) => {
  let data = { title: "GymPro CRM", body: "" };
  try {
    if (event.data) data = event.data.json();
  } catch {
    if (event.data) data = { title: "GymPro CRM", body: event.data.text() };
  }

  const title = data.title || "GymPro CRM";
  const options = {
    body: data.body || "",
    icon: "/Gympro_logo.jpeg",
    badge: "/Gympro_logo.jpeg",
    data: { url: data.url || "/" },
  };

  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || "/";

  event.waitUntil(
    clients.matchAll({ type: "window", includeUncontrolled: true }).then((windowClients) => {
      for (const client of windowClients) {
        if (client.url.includes(self.location.origin) && "focus" in client) {
          client.navigate(url);
          return client.focus();
        }
      }
      if (clients.openWindow) return clients.openWindow(url);
    })
  );
});
