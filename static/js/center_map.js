// Updated center_map.js with user location support

window.addEventListener("DOMContentLoaded", function () {
  const coordElement = document.getElementById("centerCoordinates");
  const centerName = document.getElementById("centerName")?.textContent || "Recycling Center";
  const centerAddress = document.getElementById("centerAddress")?.textContent || "";

  if (!coordElement) return;

  let coords = JSON.parse(coordElement.textContent || "[]");

  if (coords.length === 2) {
    const [lon, lat] = coords; // GeoJSON: [longitude, latitude]
    const map = L.map("map").setView([lat, lon], 14);

    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org">OpenStreetMap</a> contributors'
    }).addTo(map);

    const popupText = `<strong>${centerName}</strong><br>${centerAddress}`;
    L.marker([lat, lon]).addTo(map).bindPopup(popupText).openPopup();

    // Optional: User live location
    if (navigator.geolocation) {
      navigator.geolocation.getCurrentPosition(
        (position) => {
          const userLat = position.coords.latitude;
          const userLon = position.coords.longitude;

          const userMarker = L.marker([userLat, userLon]).addTo(map);
          userMarker.bindPopup("<strong>Your Location</strong>").openPopup();
        },
        (err) => {
          console.warn("Geolocation error:", err.message);
        },
        {
          enableHighAccuracy: true,
          timeout: 10000,
          maximumAge: 0
        }
      );
    } else {
      console.log("Geolocation not supported by this browser.");
    }
  } else {
    alert("Center coordinates are invalid or missing.");
  }
});