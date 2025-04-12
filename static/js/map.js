document.addEventListener("DOMContentLoaded", function () {
  const getLocationBtn = document.getElementById("getLocationBtn");
  if (getLocationBtn) {
    getLocationBtn.addEventListener("click", function () {
      if (navigator.geolocation) {
        navigator.geolocation.getCurrentPosition(
          function (pos) {
            const lat = pos.coords.latitude;
            const lon = pos.coords.longitude;
            window.location.href = `/recycling_centers?lat=${lat}&lon=${lon}`;
          },
          function (err) {
            alert("Could not get your location: " + err.message);
          },
          {
            enableHighAccuracy: true,
            timeout: 10000,
            maximumAge: 0
          }
        );
      } else {
        alert("Geolocation not supported by this browser.");
      }
    });
  }

  const map = L.map("map");
  let defaultLat = 20.5937;
  let defaultLon = 78.9629;
  let defaultZoom = 5;

  const userLatInput = document.getElementById("userLat");
  const userLonInput = document.getElementById("userLon");
  if (userLatInput && userLonInput) {
    const latVal = parseFloat(userLatInput.value);
    const lonVal = parseFloat(userLonInput.value);
    if (!isNaN(latVal) && !isNaN(lonVal)) {
      defaultLat = latVal;
      defaultLon = lonVal;
      defaultZoom = 13;
    }
  }

  map.setView([defaultLat, defaultLon], defaultZoom);

  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
  }).addTo(map);

  if (userLatInput && userLonInput) {
    const latVal = parseFloat(userLatInput.value);
    const lonVal = parseFloat(userLonInput.value);
    if (!isNaN(latVal) && !isNaN(lonVal)) {
      const userMarker = L.marker([latVal, lonVal]).addTo(map);
      userMarker.bindPopup("<strong>Your Location</strong>").openPopup();
    }
  }

  document.querySelectorAll(".center-card.center-item").forEach(item => {
    const lat = parseFloat(item.dataset.lat);
    const lon = parseFloat(item.dataset.lon);
    const name = item.dataset.name;
    if (!isNaN(lat) && !isNaN(lon)) {
      const marker = L.marker([lat, lon]).addTo(map);
      marker.bindPopup(`<strong>${name}</strong>`);
    }
  });
});