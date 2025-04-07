document.addEventListener("DOMContentLoaded", function () {
  // Handle "Show My Location & Sort" button
  const getLocationBtn = document.getElementById("getLocationBtn");
  if (getLocationBtn) {
    getLocationBtn.addEventListener("click", function () {
      if (navigator.geolocation) {
        navigator.geolocation.getCurrentPosition(
          function (pos) {
            const lat = pos.coords.latitude;
            const lon = pos.coords.longitude;
            window.location.href = "/recycling_centers?lat=" + lat + "&lon=" + lon;
          },
          function (err) {
            alert("Could not get your location: " + err.message);
          }
        );
      } else {
        alert("Geolocation not supported by this browser.");
      }
    });
  }

  // Initialize Leaflet map
  const map = L.map("map");
  let defaultLat = 20.5937;
  let defaultLon = 78.9629;
  let defaultZoom = 5;

  // If user location is available from hidden inputs, center the map on it
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

  // Add OpenStreetMap tiles
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; OpenStreetMap contributors'
  }).addTo(map);

  // If user location is available, add a marker for it
  if (userLatInput && userLonInput) {
    const latVal = parseFloat(userLatInput.value);
    const lonVal = parseFloat(userLonInput.value);
    if (!isNaN(latVal) && !isNaN(lonVal)) {
      const userMarker = L.marker([latVal, lonVal]).addTo(map);
      userMarker.bindPopup("<strong>Your Location</strong>").openPopup();
    }
  }

  // Add markers for each recycling center using data attributes
  const centerItems = document.querySelectorAll(".center-card.center-item");
  centerItems.forEach(function (item) {
    const latStr = item.getAttribute("data-lat");
    const lonStr = item.getAttribute("data-lon");
    const name = item.getAttribute("data-name");

    if (latStr && lonStr) {
      const cLat = parseFloat(latStr);
      const cLon = parseFloat(lonStr);
      if (!isNaN(cLat) && !isNaN(cLon)) {
        const marker = L.marker([cLat, cLon]).addTo(map);
        marker.bindPopup("<strong>" + name + "</strong>");
      }
    }
  });
});
